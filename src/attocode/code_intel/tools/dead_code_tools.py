"""Dead code detection tools for the code-intel MCP server.

Provides a ``dead_code`` tool that identifies unreferenced symbols, files,
and modules using the cross-reference index.  Three analysis levels:

- ``symbol``: Functions, classes, and methods with zero references.
- ``file``: Files with zero importers that are not entry points.
- ``module``: Directories with no external imports from outside.

Entry points (tests, CLI mains, framework routes, etc.) are automatically
excluded using filename and decorator heuristics.
"""

from __future__ import annotations

import os
import time

try:
    from attocode.code_intel.server import (
        _get_ast_service,
        _get_context_mgr,
        _get_project_dir,
        mcp,
    )
except (ImportError, AttributeError):
    # Deferred: will be available when server.py finishes loading.
    # Private helpers (_find_dead_*) don't need these imports.
    _get_ast_service = None  # type: ignore[assignment]
    _get_context_mgr = None  # type: ignore[assignment]
    _get_project_dir = None  # type: ignore[assignment]

    class _StubMCP:
        """Stub so @mcp.tool() doesn't crash during deferred import."""
        def tool(self):
            return lambda f: f
    mcp = _StubMCP()  # type: ignore[assignment]
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
)


# ---------------------------------------------------------------------------
# Entry-point heuristics
# ---------------------------------------------------------------------------

_ENTRY_POINT_FILE_PATTERNS: set[str] = {
    "main.py",
    "__main__.py",
    "__init__.py",
    "setup.py",
    "manage.py",
    "conftest.py",
}

_ENTRY_POINT_FILE_PREFIXES = ("test_",)
_ENTRY_POINT_FILE_SUFFIXES = ("_test.py",)

_ENTRY_POINT_DECORATOR_KEYWORDS: set[str] = {
    "route",
    "endpoint",
    "fixture",
    "command",
    "click",
}

_ENTRY_POINT_FUNCTION_NAMES: set[str] = {
    "main",
    "setup",
    "teardown",
}


def _is_entry_point_file(rel_path: str) -> bool:
    """Return True if *rel_path* looks like a test, CLI main, or config file."""
    basename = os.path.basename(rel_path)
    if basename in _ENTRY_POINT_FILE_PATTERNS:
        return True
    if any(basename.startswith(p) for p in _ENTRY_POINT_FILE_PREFIXES):
        return True
    if any(basename.endswith(s) for s in _ENTRY_POINT_FILE_SUFFIXES):
        return True
    return False


def _is_entry_point_symbol(
    loc: SymbolLocation,
    ast_cache: dict,
) -> bool:
    """Return True if the symbol at *loc* looks like a framework entry point.

    Checks decorator names and special function names.
    """
    # Special function names
    base_name = loc.name.rsplit(".", 1)[-1] if "." in loc.name else loc.name
    if base_name in _ENTRY_POINT_FUNCTION_NAMES:
        return True

    # Symbols defined in __init__.py are considered re-exports
    if os.path.basename(loc.file_path) == "__init__.py":
        return True

    # Check decorators from AST cache
    file_ast = ast_cache.get(loc.file_path)
    if file_ast is None:
        return False

    # Search functions and class methods for matching decorator keywords
    for func in file_ast.functions:
        if func.name == base_name or loc.qualified_name.endswith(f".{func.name}"):
            for dec in func.decorators:
                if any(kw in dec.lower() for kw in _ENTRY_POINT_DECORATOR_KEYWORDS):
                    return True

    for cls in file_ast.classes:
        if cls.name == base_name or loc.qualified_name.endswith(f".{cls.name}"):
            for dec in cls.decorators:
                if any(kw in dec.lower() for kw in _ENTRY_POINT_DECORATOR_KEYWORDS):
                    return True
        # Check methods inside the class
        for method in cls.methods:
            qname_suffix = f"{cls.name}.{method.name}"
            if loc.qualified_name.endswith(qname_suffix):
                for dec in method.decorators:
                    if any(kw in dec.lower() for kw in _ENTRY_POINT_DECORATOR_KEYWORDS):
                        return True

    return False


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def _compute_confidence(
    loc: SymbolLocation,
    index: CrossRefIndex,
    project_dir: str,
) -> float:
    """Compute a confidence score (0.0-1.0) that *loc* is truly dead code.

    Higher confidence = more likely to be safe to remove.
    """
    name = loc.name
    is_private = name.startswith("_") and not name.startswith("__")

    # Base score
    if is_private:
        confidence = 0.8
    else:
        confidence = 0.7

    # Penalty: symbol defined in __init__.py (likely a re-export)
    if os.path.basename(loc.file_path) == "__init__.py":
        confidence -= 0.3

    # Penalty: looks like a public API (no underscore prefix + exported)
    if not name.startswith("_"):
        confidence -= 0.2

    # Bonus: file hasn't been modified recently (> 180 days)
    try:
        abs_path = os.path.join(project_dir, loc.file_path)
        mtime = os.path.getmtime(abs_path)
        age_days = (time.time() - mtime) / 86400
        if age_days > 180:
            confidence += 0.1
    except OSError:
        pass

    return max(0.0, min(1.0, round(confidence, 2)))


# ---------------------------------------------------------------------------
# Dead-code finders
# ---------------------------------------------------------------------------


def _find_dead_symbols(
    index: CrossRefIndex,
    ast_cache: dict,
    project_dir: str,
    scope: str,
    entry_points: set[str],
    min_confidence: float,
    top_n: int,
) -> list[dict]:
    """Find symbols with 0 references, excluding entry points."""
    candidates: list[dict] = []

    for qname, locs in index.definitions.items():
        for loc in locs:
            # Skip if outside scope
            if scope and not loc.file_path.startswith(scope):
                continue

            # Skip user-specified entry points
            if qname in entry_points or loc.name in entry_points:
                continue

            # Skip auto-detected entry points
            if _is_entry_point_file(loc.file_path):
                continue
            if _is_entry_point_symbol(loc, ast_cache):
                continue

            # Check references: look up by both qualified name and base name
            refs_by_qname = index.references.get(qname, [])
            base_name = qname.rsplit(".", 1)[-1] if "." in qname else qname
            refs_by_base = index.references.get(base_name, [])

            # Filter out self-references (references from the same file)
            external_refs_q = [
                r for r in refs_by_qname if r.file_path != loc.file_path
            ]
            external_refs_b = [
                r for r in refs_by_base if r.file_path != loc.file_path
            ]

            # If there are any external references, it's not dead
            if external_refs_q or external_refs_b:
                continue

            # Also check if the base name has any references at all (suffix match)
            # For methods like "ClassName.method", check if "method" is referenced
            has_any_ref = False
            if "." in qname:
                for ref_name, refs in index.references.items():
                    if ref_name == base_name or ref_name.endswith(f".{base_name}"):
                        external = [
                            r for r in refs if r.file_path != loc.file_path
                        ]
                        if external:
                            has_any_ref = True
                            break
            if has_any_ref:
                continue

            # Compute confidence
            confidence = _compute_confidence(loc, index, project_dir)
            if confidence < min_confidence:
                continue

            # Determine reason
            reasons: list[str] = []
            if loc.kind == "method":
                reasons.append("method with no external callers")
            elif loc.kind == "class":
                reasons.append("class never instantiated or referenced")
            else:
                reasons.append("function never called or imported")

            if loc.name.startswith("_"):
                reasons.append("private symbol")

            candidates.append({
                "symbol": loc.qualified_name,
                "name": loc.name,
                "kind": loc.kind,
                "file": loc.file_path,
                "line": loc.start_line,
                "end_line": loc.end_line,
                "confidence": confidence,
                "reason": "; ".join(reasons),
            })

    # Sort by confidence descending, then by file/line
    candidates.sort(key=lambda c: (-c["confidence"], c["file"], c["line"]))
    return candidates[:top_n]


def _find_dead_files(
    index: CrossRefIndex,
    all_file_paths: set[str],
    scope: str,
    entry_points: set[str],
    min_confidence: float,
    top_n: int,
    project_dir: str,
) -> list[dict]:
    """Find files with 0 importers that are not entry points."""
    candidates: list[dict] = []

    for rel_path in sorted(all_file_paths):
        # Skip if outside scope
        if scope and not rel_path.startswith(scope):
            continue

        # Skip user-specified entry points
        if rel_path in entry_points:
            continue

        # Skip auto-detected entry-point files
        if _is_entry_point_file(rel_path):
            continue

        # Check importers
        importers = index.file_dependents.get(rel_path, set())
        if importers:
            continue

        # Compute file-level confidence
        basename = os.path.basename(rel_path)
        is_private = basename.startswith("_") and basename != "__init__.py"
        confidence = 0.8 if is_private else 0.7

        # Penalty for __init__.py
        if basename == "__init__.py":
            confidence -= 0.3

        # Penalty for public-looking files
        if not basename.startswith("_"):
            confidence -= 0.2

        # Bonus for old files
        try:
            abs_path = os.path.join(project_dir, rel_path)
            mtime = os.path.getmtime(abs_path)
            age_days = (time.time() - mtime) / 86400
            if age_days > 180:
                confidence += 0.1
        except OSError:
            pass

        confidence = max(0.0, min(1.0, round(confidence, 2)))
        if confidence < min_confidence:
            continue

        # Count symbols in the file
        symbol_count = len(index.file_symbols.get(rel_path, set()))
        deps_count = len(index.file_dependencies.get(rel_path, set()))

        reasons: list[str] = ["no files import this module"]
        if deps_count == 0:
            reasons.append("also has no imports (orphan)")

        candidates.append({
            "file": rel_path,
            "symbol_count": symbol_count,
            "dependency_count": deps_count,
            "confidence": confidence,
            "reason": "; ".join(reasons),
        })

    candidates.sort(key=lambda c: (-c["confidence"], c["file"]))
    return candidates[:top_n]


def _find_dead_modules(
    index: CrossRefIndex,
    all_file_paths: set[str],
    scope: str,
    entry_points: set[str],
    min_confidence: float,
    top_n: int,
    project_dir: str,
) -> list[dict]:
    """Find directories where no file is imported from outside the directory."""
    # Group files by directory
    dir_files: dict[str, set[str]] = {}
    for rel_path in all_file_paths:
        dir_name = os.path.dirname(rel_path)
        if not dir_name:
            continue  # skip root-level files
        dir_files.setdefault(dir_name, set()).add(rel_path)

    candidates: list[dict] = []

    for dir_path, files_in_dir in sorted(dir_files.items()):
        # Skip if outside scope
        if scope and not dir_path.startswith(scope):
            continue

        # Skip user-specified entry points
        if dir_path in entry_points:
            continue

        # Check if any file in this directory is imported from outside
        has_external_importer = False
        for f in files_in_dir:
            importers = index.file_dependents.get(f, set())
            for imp in importers:
                if os.path.dirname(imp) != dir_path:
                    has_external_importer = True
                    break
            if has_external_importer:
                break

        if has_external_importer:
            continue

        # Check if any file in the directory is an entry point
        has_entry_point = any(_is_entry_point_file(f) for f in files_in_dir)

        # Base confidence
        confidence = 0.7
        if has_entry_point:
            confidence -= 0.3  # might be a standalone executable package

        # Bonus for old directories
        try:
            newest_mtime = 0.0
            for f in files_in_dir:
                abs_path = os.path.join(project_dir, f)
                try:
                    mt = os.path.getmtime(abs_path)
                    newest_mtime = max(newest_mtime, mt)
                except OSError:
                    pass
            if newest_mtime > 0:
                age_days = (time.time() - newest_mtime) / 86400
                if age_days > 180:
                    confidence += 0.1
        except OSError:
            pass

        confidence = max(0.0, min(1.0, round(confidence, 2)))
        if confidence < min_confidence:
            continue

        # Count total symbols across all files in directory
        total_symbols = sum(
            len(index.file_symbols.get(f, set())) for f in files_in_dir
        )

        reasons: list[str] = [
            f"no external imports into this directory ({len(files_in_dir)} files)"
        ]
        if has_entry_point:
            reasons.append("contains entry-point files (lower confidence)")

        candidates.append({
            "module": dir_path,
            "file_count": len(files_in_dir),
            "symbol_count": total_symbols,
            "confidence": confidence,
            "reason": "; ".join(reasons),
        })

    candidates.sort(key=lambda c: (-c["confidence"], c["module"]))
    return candidates[:top_n]


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


@mcp.tool()
def dead_code(
    scope: str = "",
    entry_points: list[str] | None = None,
    level: str = "symbol",
    min_confidence: float = 0.5,
    top_n: int = 30,
) -> str:
    """Detect potentially dead (unreferenced) code in the project.

    Scans the cross-reference index for symbols, files, or modules that
    have zero external references and are not detected as entry points.
    Results are ranked by confidence score.

    Args:
        scope: Restrict analysis to files under this directory prefix
               (e.g. "src/mypackage/"). Empty string means whole project.
        entry_points: Additional qualified names or file paths to treat as
                      entry points (never flagged as dead). Auto-detected
                      entry points (tests, mains, framework routes) are
                      always excluded.
        level: Analysis granularity. One of:
               - "symbol": individual functions, classes, methods (default)
               - "file": entire files with no importers
               - "module": directories with no external imports
        min_confidence: Minimum confidence threshold (0.0-1.0). Only report
                        items at or above this score. Default 0.5.
        top_n: Maximum number of results to return. Default 30.
    """
    valid_levels = {"symbol", "file", "module"}
    if level not in valid_levels:
        opts = ", ".join(sorted(valid_levels))
        return f"Error: invalid level '{level}'. Must be one of: {opts}"

    min_confidence = max(0.0, min(1.0, min_confidence))
    top_n = max(1, min(200, top_n))

    svc = _get_ast_service()
    index = svc._index
    ast_cache = svc._ast_cache
    project_dir = _get_project_dir()

    ctx = _get_context_mgr()
    all_file_paths = {fi.relative_path for fi in ctx._files}

    ep_set = set(entry_points) if entry_points else set()

    # Normalize scope
    if scope and not scope.endswith("/"):
        scope = scope + "/"

    if level == "symbol":
        items = _find_dead_symbols(
            index, ast_cache, project_dir, scope, ep_set,
            min_confidence, top_n,
        )
        return _format_symbol_results(items, scope)
    elif level == "file":
        items = _find_dead_files(
            index, all_file_paths, scope, ep_set,
            min_confidence, top_n, project_dir,
        )
        return _format_file_results(items, scope)
    else:  # module
        items = _find_dead_modules(
            index, all_file_paths, scope, ep_set,
            min_confidence, top_n, project_dir,
        )
        return _format_module_results(items, scope)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_symbol_results(items: list[dict], scope: str) -> str:
    """Format dead symbol results as ranked text output."""
    scope_label = f" in {scope}" if scope else ""
    if not items:
        return f"No dead symbols detected{scope_label}."

    lines = [f"Dead symbols detected{scope_label} ({len(items)} results):\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"  {i:2d}. [{item['confidence']:.2f}] {item['kind']} {item['symbol']}\n"
            f"      {item['file']}:{item['line']}\n"
            f"      Reason: {item['reason']}"
        )
    return "\n".join(lines)


def _format_file_results(items: list[dict], scope: str) -> str:
    """Format dead file results as ranked text output."""
    scope_label = f" in {scope}" if scope else ""
    if not items:
        return f"No dead files detected{scope_label}."

    lines = [f"Dead files detected{scope_label} ({len(items)} results):\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"  {i:2d}. [{item['confidence']:.2f}] {item['file']}\n"
            f"      {item['symbol_count']} symbols, "
            f"{item['dependency_count']} dependencies\n"
            f"      Reason: {item['reason']}"
        )
    return "\n".join(lines)


def _format_module_results(items: list[dict], scope: str) -> str:
    """Format dead module results as ranked text output."""
    scope_label = f" in {scope}" if scope else ""
    if not items:
        return f"No dead modules detected{scope_label}."

    lines = [f"Dead modules detected{scope_label} ({len(items)} results):\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"  {i:2d}. [{item['confidence']:.2f}] {item['module']}/\n"
            f"      {item['file_count']} files, "
            f"{item['symbol_count']} symbols\n"
            f"      Reason: {item['reason']}"
        )
    return "\n".join(lines)
