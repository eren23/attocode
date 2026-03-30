"""Distillation tools for the code-intel MCP server.

Provides a ``distill`` tool that compresses codebase information at
three fidelity levels: full (existing repo_map), signatures (public API
surface), and structure (file tree + import graph).
"""

from __future__ import annotations

import os
from collections import deque

from attocode.code_intel._shared import (
    _get_ast_service,
    _get_context_mgr,
    _get_remote_service,
    mcp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_public_name(name: str) -> bool:
    """Return True if *name* looks public (no leading underscore)."""
    return not name.startswith("_")


def _extract_signatures(
    ast_cache: dict,
    rel_paths: list[str],
    max_tokens: int,
) -> str:
    """Extract public API surface from AST cache for *rel_paths*.

    Produces compact Python-like signatures for public functions, classes,
    and their methods.  Each function includes parameter names + types and
    return type.  Docstrings are reduced to first line only.

    Uses ``len(text) / 3.5`` token estimation (same as ``repo_map``).
    """
    sections: list[str] = []
    token_est = 0

    for rel in rel_paths:
        file_ast = ast_cache.get(rel)
        if file_ast is None:
            continue

        file_lines: list[str] = [f"# {rel}"]
        has_content = False

        # Public top-level functions
        for fn in file_ast.functions:
            if fn.visibility != "public" and not _is_public_name(fn.name):
                continue

            sig = _format_function_sig(fn)
            file_lines.append(sig)

            # First-line docstring
            doc_line = _first_line_docstring(fn.docstring)
            if doc_line:
                file_lines.append(f'    """{doc_line}"""')

            has_content = True

        # Public classes
        for cls in file_ast.classes:
            if not _is_public_name(cls.name):
                continue

            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            file_lines.append(f"class {cls.name}{bases}:")

            # Class docstring
            cls_doc = _first_line_docstring(cls.docstring)
            if cls_doc:
                file_lines.append(f'    """{cls_doc}"""')

            # Public methods
            method_count = 0
            for method in cls.methods:
                if method.visibility != "public" and not _is_public_name(method.name):
                    continue

                sig = _format_function_sig(method, indent=4)
                file_lines.append(sig)

                m_doc = _first_line_docstring(method.docstring)
                if m_doc:
                    file_lines.append(f'        """{m_doc}"""')

                method_count += 1

            if method_count == 0 and not cls_doc:
                file_lines.append("    ...")

            has_content = True

        if not has_content:
            continue

        section_text = "\n".join(file_lines)
        section_tokens = int(len(section_text) / 3.5)

        if token_est + section_tokens > max_tokens and sections:
            remaining = len(rel_paths) - len(sections)
            if remaining > 0:
                sections.append(f"\n# ... {remaining} more file(s) omitted (token budget)")
            break

        sections.append(section_text)
        token_est += section_tokens

    return "\n\n".join(sections)


def _format_function_sig(fn, indent: int = 0) -> str:
    """Format a FunctionDef as a compact signature line."""
    prefix = " " * indent
    async_kw = "async " if fn.is_async else ""

    # Build parameter list from detailed parameters if available
    if fn.parameters:
        params = []
        for p in fn.parameters:
            part = p.name
            if p.type_annotation:
                part += f": {p.type_annotation}"
            if p.default_value:
                part += f" = {p.default_value}"
            if p.is_rest:
                part = f"*{part}"
            elif p.is_kwargs:
                part = f"**{part}"
            params.append(part)
        param_str = ", ".join(params)
    elif fn.params:
        # Fallback to simple param names
        param_str = ", ".join(fn.params)
    else:
        param_str = ""

    ret = f" -> {fn.return_type}" if fn.return_type else ""
    return f"{prefix}{async_kw}def {fn.name}({param_str}){ret}: ..."


def _first_line_docstring(docstring: str) -> str:
    """Return the first non-empty line of a docstring, or ''."""
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        stripped = line.strip().strip('"').strip("'").strip()
        if stripped:
            # Truncate very long first lines
            if len(stripped) > 120:
                return stripped[:117] + "..."
            return stripped
    return ""


def _build_structure(
    files: list,
    dep_graph,
    rel_paths: list[str] | None,
    max_tokens: int,
) -> str:
    """Build file tree + import graph adjacency list.

    This is the maximum compression level (~90%+).
    """
    sections: list[str] = []

    # File tree
    tree_files = sorted(rel_paths) if rel_paths else sorted(fi.relative_path for fi in files)

    tree_lines = ["# File tree"]
    for path in tree_files:
        tree_lines.append(f"  {path}")
    tree_text = "\n".join(tree_lines)
    sections.append(tree_text)

    # Import graph adjacency list
    if dep_graph is not None:
        graph_lines = ["# Import graph (file -> imports)"]
        graph_set = set(rel_paths) if rel_paths else None
        for src in sorted(dep_graph.forward.keys()):
            if graph_set is not None and src not in graph_set:
                continue
            targets = dep_graph.forward.get(src, set())
            if graph_set is not None:
                targets = targets & graph_set
            if targets:
                target_list = ", ".join(sorted(targets))
                graph_lines.append(f"  {src} -> {target_list}")

        if len(graph_lines) > 1:
            graph_text = "\n".join(graph_lines)
            sections.append(graph_text)

    result = "\n\n".join(sections)

    # Truncate if over budget
    max_chars = int(max_tokens * 3.5)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n# ... truncated (token budget)"

    return result


def _expand_by_depth(
    center_files: list[str],
    dep_graph,
    depth: int,
) -> list[str]:
    """BFS expand from center files through dependency graph up to *depth* hops."""
    if dep_graph is None:
        return center_files

    visited: set[str] = set(center_files)
    queue: deque[tuple[str, int]] = deque()
    for f in center_files:
        queue.append((f, 0))

    while queue:
        current, d = queue.popleft()
        if d >= depth:
            continue

        # Forward: files this one imports
        for dep in dep_graph.get_imports(current):
            if dep not in visited:
                visited.add(dep)
                queue.append((dep, d + 1))

        # Reverse: files that import this one
        for dep in dep_graph.get_importers(current):
            if dep not in visited:
                visited.add(dep)
                queue.append((dep, d + 1))

    return sorted(visited)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


@mcp.tool()
def distill(
    files: list[str] | None = None,
    depth: int = 1,
    level: str = "signatures",
    max_tokens: int = 4000,
) -> str:
    """Compress codebase information at varying fidelity levels.

    Three distillation levels for different context budget needs:
    - "full": Complete repo map with symbols (delegates to repo_map)
    - "signatures": Public API surface — function/method signatures,
      class definitions, type hints, first-line docstrings (~70% compression)
    - "structure": File tree + import graph adjacency list only (~90%+ compression)

    File selection:
    - If files are specified, includes those files plus neighbors up to
      `depth` hops via the dependency graph.
    - If files is None, auto-selects the most important files (by PageRank
      importance) that fit within the token budget.

    Args:
        files: Specific file paths to distill (relative to project root).
            When None, auto-selects by importance.
        depth: Number of dependency graph hops to expand from specified files
            (default 1, max 3). Ignored when files is None.
        level: Distillation level — "full", "signatures", or "structure".
        max_tokens: Token budget for the output (default 4000).
    """
    remote = _get_remote_service()
    if remote is not None:
        return remote.distill(
            files=files,
            depth=depth,
            level=level,
            max_tokens=max_tokens,
        )

    # Level: full — delegate to existing repo_map
    if level == "full":
        from attocode.code_intel.tools.navigation_tools import repo_map as _repo_map

        return _repo_map(include_symbols=True, max_tokens=max_tokens)

    ctx = _get_context_mgr()
    all_files = ctx._files

    if not all_files:
        return "No files discovered in this project."

    svc = _get_ast_service()
    ast_cache = svc._ast_cache
    dep_graph = ctx.dependency_graph
    depth = min(depth, 3)

    # Determine which files to include
    if files is not None:
        # Normalize to relative paths
        project_dir = ctx.root_dir
        center_rels: list[str] = []
        for f in files:
            if os.path.isabs(f):
                try:
                    rel = os.path.relpath(f, project_dir)
                except ValueError:
                    rel = f
            else:
                rel = f
            center_rels.append(rel)

        # Expand by dependency depth
        if depth > 0 and dep_graph is not None:
            selected = _expand_by_depth(center_rels, dep_graph, depth)
        else:
            selected = sorted(set(center_rels))
    else:
        # Auto-select by importance (PageRank), fitting token budget
        sorted_files = sorted(all_files, key=lambda fi: fi.importance, reverse=True)

        # For signatures, estimate ~80 chars per file on average; for structure ~40 chars
        avg_chars = 80 if level == "signatures" else 40
        max_files_estimate = int(max_tokens * 3.5 / avg_chars)
        selected = [fi.relative_path for fi in sorted_files[:max_files_estimate]]

    if not selected:
        return "No files matched the selection criteria."

    # Generate output based on level
    if level == "signatures":
        output = _extract_signatures(ast_cache, selected, max_tokens)
    elif level == "structure":
        output = _build_structure(all_files, dep_graph, selected, max_tokens)
    else:
        return f"Unknown distillation level: '{level}'. Use 'full', 'signatures', or 'structure'."

    if not output:
        return "No content extracted (files may not have parseable ASTs)."

    # Add summary footer
    footer = f"\n\n({len(selected)} files, level={level}, ~{int(len(output) / 3.5)} tokens)"
    return output + footer
