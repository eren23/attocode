"""MCP server exposing Attocode's code intelligence capabilities.

Provides 27 tools for deep codebase understanding:
- bootstrap: All-in-one orientation (summary + map + conventions + search)
- relevant_context: Subgraph capsule for file(s) with neighbors and symbols
- repo_map: Token-budgeted file tree with symbols
- symbols: List symbols in a file
- search_symbols: Fuzzy symbol search across codebase
- dependencies: File import/importer relationships
- impact_analysis: Transitive impact of file changes (BFS)
- cross_references: Symbol definitions + usage sites
- file_analysis: Detailed single-file analysis
- dependency_graph: Dependency graph from a starting file
- project_summary: High-level project overview (CLAUDE.md bootstrap)
- hotspots: Risk/complexity analysis with ranked hotspots
- conventions: Code style and convention detection (with optional directory scoping)
- lsp_definition: Type-resolved go-to-definition
- lsp_references: All references with type awareness
- lsp_hover: Type signature + docs for symbol
- lsp_diagnostics: Errors/warnings from language server
- explore_codebase: Hierarchical drill-down navigation
- security_scan: Secret/anti-pattern/dependency scanning
- semantic_search: Natural language code search
- recall: Retrieve relevant project learnings
- record_learning: Record patterns/conventions/gotchas
- learning_feedback: Mark learnings as helpful/unhelpful
- list_learnings: Browse stored learnings

Usage::

    attocode-code-intel --project /path/to/repo
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Error: 'mcp' package not installed. "
        "Reinstall with: uv tool install --force --reinstall --from . attocode",
        file=sys.stderr,
    )
    sys.exit(1)

logger = logging.getLogger(__name__)

mcp = FastMCP("attocode-code-intel")

# ---------------------------------------------------------------------------
# MCP Resource: Agent Guidelines
# ---------------------------------------------------------------------------

_GUIDELINES_PATH = Path(__file__).parent / "GUIDELINES.md"


@mcp.resource("attocode://guidelines")
def guidelines_resource() -> str:
    """Agent guidelines for using code intelligence tools effectively."""
    try:
        return _GUIDELINES_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Guidelines file not found."


# Lazily initialized singletons
_ast_service = None
_context_mgr = None
_code_analyzer = None
def _get_project_dir() -> str:
    """Get the project directory from env var or raise."""
    project_dir = os.environ.get("ATTOCODE_PROJECT_DIR", "")
    if not project_dir:
        raise RuntimeError(
            "ATTOCODE_PROJECT_DIR not set. "
            "Pass --project <path> or set the environment variable."
        )
    return os.path.abspath(project_dir)


def _get_ast_service():
    """Lazily initialize and return the ASTService singleton."""
    global _ast_service
    if _ast_service is None:
        from attocode.integrations.context.ast_service import ASTService

        project_dir = _get_project_dir()
        _ast_service = ASTService.get_instance(project_dir)
        if not _ast_service.initialized:
            logger.info("Initializing ASTService for %s...", project_dir)
            _ast_service.initialize()
            logger.info(
                "ASTService ready: %d files indexed",
                len(_ast_service._ast_cache),
            )
    return _ast_service


def _get_context_mgr():
    """Lazily initialize and return the CodebaseContextManager."""
    global _context_mgr
    if _context_mgr is None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        project_dir = _get_project_dir()
        _context_mgr = CodebaseContextManager(root_dir=project_dir)
        _context_mgr.discover_files()
    return _context_mgr


def _get_code_analyzer():
    """Lazily initialize and return the CodeAnalyzer."""
    global _code_analyzer
    if _code_analyzer is None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        _code_analyzer = CodeAnalyzer()
    return _code_analyzer


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------

# Framework/library patterns for tech stack detection
FRAMEWORK_PATTERNS: dict[str, str] = {
    "flask": "Flask",
    "django": "Django",
    "fastapi": "FastAPI",
    "starlette": "Starlette",
    "uvicorn": "Uvicorn",
    "gunicorn": "Gunicorn",
    "celery": "Celery",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "pytest": "pytest",
    "unittest": "unittest",
    "click": "Click",
    "typer": "Typer",
    "textual": "Textual",
    "rich": "Rich",
    "httpx": "httpx",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "asyncio": "asyncio",
    "numpy": "NumPy",
    "pandas": "pandas",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "transformers": "Transformers",
    "anthropic": "Anthropic SDK",
    "openai": "OpenAI SDK",
    "mcp": "MCP",
    "react": "React",
    "express": "Express",
    "next": "Next.js",
    "vue": "Vue",
    "angular": "Angular",
    "svelte": "Svelte",
    "dataclasses": "dataclasses",
    "attrs": "attrs",
    "marshmallow": "Marshmallow",
    "alembic": "Alembic",
    "boto3": "AWS SDK (boto3)",
    "google.cloud": "Google Cloud SDK",
}

_SNAKE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")

_ENTRY_BASENAMES = {
    "main.py", "cli.py", "app.py", "server.py",
    "index.ts", "index.js", "main.ts", "main.go", "lib.rs",
}
_CONFIG_BASENAMES = {
    "pyproject.toml", "package.json", "Cargo.toml",
    "setup.py", "setup.cfg", "go.mod",
}


@dataclass(slots=True)
class _FileMetrics:
    path: str
    line_count: int = 0
    symbol_count: int = 0
    public_symbols: int = 0
    fan_in: int = 0
    fan_out: int = 0
    density: float = 0.0
    composite: float = 0.0
    categories: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _FunctionMetrics:
    file_path: str
    name: str
    line_count: int
    param_count: int
    is_public: bool
    has_return_type: bool


def _detect_project_name(project_dir: str) -> str:
    """Detect project name from config files or directory basename."""
    for cfg_name, pattern in [
        ("pyproject.toml", r'name\s*=\s*"([^"]+)"'),
        ("package.json", r'"name"\s*:\s*"([^"]+)"'),
        ("Cargo.toml", r'name\s*=\s*"([^"]+)"'),
        ("setup.cfg", r'name\s*=\s*(.+)'),
    ]:
        cfg_path = os.path.join(project_dir, cfg_name)
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8", errors="replace") as f:
                    content = f.read(4096)
                m = re.search(pattern, content)
                if m:
                    return m.group(1).strip()
            except OSError:
                pass
    return os.path.basename(os.path.abspath(project_dir))


def _find_entry_points(files: list, index) -> list[tuple[str, str]]:
    """Find likely entry points. Returns list of (path, reason)."""
    results: list[tuple[str, str]] = []
    seen = set()
    for fi in files:
        rel = fi.relative_path
        basename = os.path.basename(rel)
        if fi.importance >= 0.8 and rel not in seen:
            results.append((rel, f"importance={fi.importance:.1f}"))
            seen.add(rel)
        elif basename in _ENTRY_BASENAMES and rel not in seen:
            results.append((rel, "entry filename"))
            seen.add(rel)
    return results[:15]


def _find_hub_files(files: list, index, top_n: int = 10) -> list[tuple[str, int, int]]:
    """Find most-depended-on files. Returns (path, fan_in, fan_out)."""
    metrics = []
    for fi in files:
        rel = fi.relative_path
        fan_in = len(index.file_dependents.get(rel, set()))
        fan_out = len(index.file_dependencies.get(rel, set()))
        if fan_in > 0:
            metrics.append((rel, fan_in, fan_out))
    metrics.sort(key=lambda x: x[1], reverse=True)
    return metrics[:top_n]


def _summarize_directories(files: list) -> list[tuple[str, int, int]]:
    """Group files by top-level directory. Returns (dir, file_count, total_lines)."""
    dir_stats: dict[str, tuple[int, int]] = {}
    for fi in files:
        parts = fi.relative_path.split("/")
        top_dir = parts[0] if len(parts) > 1 else "(root)"
        count, lines = dir_stats.get(top_dir, (0, 0))
        dir_stats[top_dir] = (count + 1, lines + fi.line_count)
    result = [(d, c, loc) for d, (c, loc) in dir_stats.items()]
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def _classify_layers(files: list, index) -> dict[str, list[str]]:
    """Classify non-test files into dependency layers."""
    layers: dict[str, list[str]] = {"foundation": [], "integration": [], "leaf": []}
    for fi in files:
        if fi.is_test or fi.is_config:
            continue
        rel = fi.relative_path
        fan_in = len(index.file_dependents.get(rel, set()))
        fan_out = len(index.file_dependencies.get(rel, set()))
        if fan_in >= 5 and fan_out <= 3:
            layers["foundation"].append(rel)
        elif fan_in >= 2 and fan_out >= 2:
            layers["integration"].append(rel)
        elif fan_in <= 1 and fan_out >= 3:
            layers["leaf"].append(rel)
    return layers


def _detect_tech_stack(ast_cache: dict) -> list[str]:
    """Detect frameworks/libraries from import statements."""
    found: Counter = Counter()
    for file_ast in ast_cache.values():
        for imp in file_ast.imports:
            mod = imp.module.split(".")[0] if imp.module else ""
            if mod in FRAMEWORK_PATTERNS:
                found[FRAMEWORK_PATTERNS[mod]] += 1
    # Return sorted by frequency
    return [name for name, _ in found.most_common()]


def _detect_build_system(files: list) -> str:
    """Detect build system from config file presence."""
    basenames = {os.path.basename(fi.relative_path) for fi in files}
    systems = []
    if "pyproject.toml" in basenames:
        systems.append("pyproject.toml")
    if "setup.py" in basenames or "setup.cfg" in basenames:
        systems.append("setuptools")
    if "package.json" in basenames:
        systems.append("npm/node")
    if "Cargo.toml" in basenames:
        systems.append("Cargo (Rust)")
    if "go.mod" in basenames:
        systems.append("Go modules")
    if "Makefile" in basenames or "makefile" in basenames:
        systems.append("Make")
    if "CMakeLists.txt" in basenames:
        systems.append("CMake")
    if "Dockerfile" in basenames:
        systems.append("Docker")
    return ", ".join(systems) if systems else "unknown"


def _is_snake_case(name: str) -> bool:
    return bool(_SNAKE_RE.match(name)) and "_" in name


def _is_camel_case(name: str) -> bool:
    return bool(_CAMEL_RE.match(name)) and name != name.lower()


def _percentile_ranks(values: list[float]) -> list[float]:
    """Return percentile rank (0.0-1.0) for each value in the input list.

    Uses average-rank method for ties. Returns all zeros for empty/single-value lists.
    """
    n = len(values)
    if n <= 1:
        return [0.0] * n
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank / (n - 1) if n > 1 else 0.0
        i = j + 1
    return ranks


def _compute_function_hotspots(ast_cache: dict, top_n: int = 10) -> list[_FunctionMetrics]:
    """Find the longest/most complex functions across the codebase."""
    all_fns: list[_FunctionMetrics] = []
    for rel, file_ast in ast_cache.items():
        for fn in file_ast.functions:
            lc = fn.end_line - fn.start_line + 1
            all_fns.append(_FunctionMetrics(
                file_path=rel,
                name=fn.name,
                line_count=lc,
                param_count=len(fn.parameters),
                is_public=fn.visibility == "public",
                has_return_type=bool(fn.return_type),
            ))
        for cls in file_ast.classes:
            for method in cls.methods:
                lc = method.end_line - method.start_line + 1
                all_fns.append(_FunctionMetrics(
                    file_path=rel,
                    name=f"{cls.name}.{method.name}",
                    line_count=lc,
                    param_count=len(method.parameters),
                    is_public=method.visibility == "public",
                    has_return_type=bool(method.return_type),
                ))
    def _composite(f: _FunctionMetrics) -> float:
        return (f.line_count / 50) * 0.5 + f.param_count * 0.3 + (0.0 if f.has_return_type else 0.2)

    all_fns.sort(key=_composite, reverse=True)
    return all_fns[:top_n]


def _compute_file_metrics(files: list, index, ast_cache: dict) -> list[_FileMetrics]:
    """Compute composite metrics for all files using percentile-based scoring."""
    # First pass: collect raw values for all eligible files
    raw: list[dict] = []
    for fi in files:
        if fi.is_config:
            continue
        rel = fi.relative_path
        lc = fi.line_count
        if lc == 0:
            continue

        file_ast = ast_cache.get(rel)
        if file_ast is not None:
            sym_count = file_ast.symbol_count
            # Count public symbols (visibility == "public")
            pub = sum(1 for fn in file_ast.functions if fn.visibility == "public")
            pub += sum(1 for cls in file_ast.classes if not cls.name.startswith("_"))
        else:
            sym_count = len(index.file_symbols.get(rel, set()))
            pub = sym_count  # assume all public without AST

        fan_in = len(index.file_dependents.get(rel, set()))
        fan_out = len(index.file_dependencies.get(rel, set()))
        density = sym_count / lc * 100 if lc > 0 else 0.0

        raw.append({
            "path": rel,
            "line_count": lc,
            "symbol_count": sym_count,
            "public_symbols": pub,
            "fan_in": fan_in,
            "fan_out": fan_out,
            "density": density,
        })

    if not raw:
        return []

    # Second pass: compute percentile ranks for each metric
    lines_pct = _percentile_ranks([r["line_count"] for r in raw])
    sym_pct = _percentile_ranks([r["symbol_count"] for r in raw])
    fan_in_pct = _percentile_ranks([r["fan_in"] for r in raw])
    fan_out_pct = _percentile_ranks([r["fan_out"] for r in raw])
    density_pct = _percentile_ranks([r["density"] for r in raw])

    # Adaptive thresholds: P90 with minimum floors
    n = len(raw)
    p90_idx = int(0.9 * (n - 1))

    sorted_lines = sorted(r["line_count"] for r in raw)
    sorted_syms = sorted(r["symbol_count"] for r in raw)
    sorted_pub = sorted(r["public_symbols"] for r in raw)
    sorted_fan_in = sorted(r["fan_in"] for r in raw)
    sorted_fan_out = sorted(r["fan_out"] for r in raw)

    thresh_lines = max(sorted_lines[p90_idx], 200)
    thresh_syms = max(sorted_syms[p90_idx], 10)
    thresh_pub = max(sorted_pub[p90_idx], 10)
    thresh_fan_in = max(sorted_fan_in[p90_idx], 3)
    thresh_fan_out = max(sorted_fan_out[p90_idx], 5)

    # Third pass: build results with percentile composite and adaptive categories
    results: list[_FileMetrics] = []
    for i, r in enumerate(raw):
        composite = (
            lines_pct[i] * 0.25
            + sym_pct[i] * 0.20
            + fan_in_pct[i] * 0.30
            + fan_out_pct[i] * 0.15
            + density_pct[i] * 0.10
        )

        cats: list[str] = []
        if r["line_count"] >= thresh_lines and r["symbol_count"] >= thresh_syms:
            cats.append("god-file")
        if r["fan_in"] >= thresh_fan_in:
            cats.append("hub")
        if r["fan_out"] >= thresh_fan_out:
            cats.append("coupling-magnet")
        if r["public_symbols"] >= thresh_pub:
            cats.append("wide-api")

        results.append(_FileMetrics(
            path=r["path"],
            line_count=r["line_count"],
            symbol_count=r["symbol_count"],
            public_symbols=r["public_symbols"],
            fan_in=r["fan_in"],
            fan_out=r["fan_out"],
            density=round(r["density"], 1),
            composite=round(composite, 3),
            categories=cats,
        ))
    return results


def _analyze_conventions(ast_cache: dict, sample_rels: list[str]) -> dict:
    """Analyze coding conventions across sampled files."""
    stats: dict = {
        "total_functions": 0,
        "snake_names": 0,
        "camel_names": 0,
        "typed_return": 0,
        "typed_params": 0,
        "total_params": 0,
        "has_docstring_fn": 0,
        "has_docstring_cls": 0,
        "total_classes": 0,
        "async_count": 0,
        "from_imports": 0,
        "plain_imports": 0,
        "relative_imports": 0,
        "total_imports": 0,
        "decorator_counts": Counter(),
        "dataclass_count": 0,
        "slots_dataclass_count": 0,
        "frozen_dataclass_count": 0,
        "abstract_count": 0,
        "base_classes": Counter(),
        "file_sizes": [],
        "files_per_dir": Counter(),
        # New stats
        "exception_classes": [],  # list of (name, bases)
        "all_exports_count": 0,
        "private_functions": 0,
        "staticmethod_count": 0,
        "classmethod_count": 0,
        "property_count": 0,
    }

    for rel in sample_rels:
        file_ast = ast_cache.get(rel)
        if file_ast is None:
            continue

        stats["file_sizes"].append(file_ast.line_count)
        parts = rel.split("/")
        dir_name = parts[0] if len(parts) > 1 else "(root)"
        stats["files_per_dir"][dir_name] += 1

        # Check for __all__ in top-level vars
        if "__all__" in file_ast.top_level_vars:
            stats["all_exports_count"] += 1

        # Functions
        all_fns = list(file_ast.functions)
        for cls in file_ast.classes:
            all_fns.extend(cls.methods)

        for fn in all_fns:
            stats["total_functions"] += 1
            if _is_snake_case(fn.name):
                stats["snake_names"] += 1
            elif _is_camel_case(fn.name):
                stats["camel_names"] += 1
            if fn.return_type:
                stats["typed_return"] += 1
            for p in fn.parameters:
                stats["total_params"] += 1
                if p.type_annotation:
                    stats["typed_params"] += 1
            if fn.docstring:
                stats["has_docstring_fn"] += 1
            if fn.is_async:
                stats["async_count"] += 1
            if fn.visibility != "public":
                stats["private_functions"] += 1
            if fn.is_staticmethod:
                stats["staticmethod_count"] += 1
            if fn.is_classmethod:
                stats["classmethod_count"] += 1
            if fn.is_property:
                stats["property_count"] += 1
            for dec in fn.decorators:
                stats["decorator_counts"][dec] += 1

        # Classes
        for cls in file_ast.classes:
            stats["total_classes"] += 1
            if cls.docstring:
                stats["has_docstring_cls"] += 1
            if cls.is_abstract:
                stats["abstract_count"] += 1
            for dec in cls.decorators:
                stats["decorator_counts"][dec] += 1
                if "dataclass" in dec:
                    stats["dataclass_count"] += 1
                    if "slots=True" in dec:
                        stats["slots_dataclass_count"] += 1
                    if "frozen=True" in dec:
                        stats["frozen_dataclass_count"] += 1
            for base in cls.bases:
                if base not in ("object",):
                    stats["base_classes"][base] += 1
            # Detect exception subclasses
            is_exception = any(
                "Exception" in b or "Error" in b
                for b in cls.bases
            )
            if is_exception:
                stats["exception_classes"].append((cls.name, list(cls.bases)))

        # Imports
        for imp in file_ast.imports:
            stats["total_imports"] += 1
            if imp.is_from:
                stats["from_imports"] += 1
                if imp.module.startswith("."):
                    stats["relative_imports"] += 1
            else:
                stats["plain_imports"] += 1

    return stats


def _format_conventions(stats: dict, dir_stats: dict[str, dict] | None = None) -> str:
    """Format convention stats into readable output."""
    sections: list[str] = []

    # Naming
    total_named = stats["snake_names"] + stats["camel_names"]
    if total_named > 0:
        snake_pct = stats["snake_names"] / total_named * 100
        sections.append(
            f"Naming: {snake_pct:.0f}% snake_case, {100 - snake_pct:.0f}% camelCase "
            f"({total_named} functions analyzed)"
        )

    # Type hints
    total_fn = stats["total_functions"]
    if total_fn > 0:
        ret_pct = stats["typed_return"] / total_fn * 100
        lines = [f"Type hints: {ret_pct:.0f}% functions have return types"]
        if stats["total_params"] > 0:
            param_pct = stats["typed_params"] / stats["total_params"] * 100
            lines.append(f"  {param_pct:.0f}% parameters have type annotations")
        sections.append("\n".join(lines))

    # Docstrings
    if total_fn > 0:
        fn_pct = stats["has_docstring_fn"] / total_fn * 100
        line = f"Docstrings: {fn_pct:.0f}% of functions"
        if stats["total_classes"] > 0:
            cls_pct = stats["has_docstring_cls"] / stats["total_classes"] * 100
            line += f", {cls_pct:.0f}% of classes"
        sections.append(line)

    # Visibility
    if total_fn > 0 and stats.get("private_functions", 0) > 0:
        pub_count = total_fn - stats["private_functions"]
        pub_pct = pub_count / total_fn * 100
        priv_pct = stats["private_functions"] / total_fn * 100
        sections.append(f"Visibility: {pub_pct:.0f}% public, {priv_pct:.0f}% private")

    # Method types
    method_parts = []
    if stats.get("staticmethod_count", 0) > 0:
        method_parts.append(f"{stats['staticmethod_count']} @staticmethod")
    if stats.get("classmethod_count", 0) > 0:
        method_parts.append(f"{stats['classmethod_count']} @classmethod")
    if stats.get("property_count", 0) > 0:
        method_parts.append(f"{stats['property_count']} @property")
    if method_parts:
        sections.append("Method types: " + ", ".join(method_parts))

    # Async
    if total_fn > 0 and stats["async_count"] > 0:
        async_pct = stats["async_count"] / total_fn * 100
        async_n = stats["async_count"]
        sections.append(
            f"Async: {async_pct:.0f}% of functions are async"
            f" ({async_n}/{total_fn})"
        )

    # Imports
    total_imp = stats["total_imports"]
    if total_imp > 0:
        from_pct = stats["from_imports"] / total_imp * 100
        line = f"Imports: {from_pct:.0f}% use 'from X import Y' style"
        if stats["relative_imports"] > 0:
            rel_pct = stats["relative_imports"] / total_imp * 100
            line += f", {rel_pct:.0f}% relative imports"
        sections.append(line)

    # Module exports (__all__)
    if stats.get("all_exports_count", 0) > 0:
        sections.append(f"Module exports: {stats['all_exports_count']} files define __all__")

    # Decorators
    top_decs = stats["decorator_counts"].most_common(8)
    if top_decs:
        dec_lines = ["Popular decorators:"]
        for dec, count in top_decs:
            dec_lines.append(f"  @{dec} ({count}x)")
        sections.append("\n".join(dec_lines))

    # Class patterns
    cls_lines = []
    if stats["dataclass_count"] > 0:
        dc_line = f"  dataclasses: {stats['dataclass_count']}"
        extras = []
        if stats.get("slots_dataclass_count", 0) > 0:
            extras.append(f"{stats['slots_dataclass_count']} with slots=True")
        if stats.get("frozen_dataclass_count", 0) > 0:
            extras.append(f"{stats['frozen_dataclass_count']} frozen")
        if extras:
            dc_line += f" ({', '.join(extras)})"
        cls_lines.append(dc_line)
    if stats["abstract_count"] > 0:
        cls_lines.append(f"  abstract classes: {stats['abstract_count']}")
    top_bases = stats["base_classes"].most_common(5)
    if top_bases:
        cls_lines.append("  common bases: " + ", ".join(f"{b} ({c}x)" for b, c in top_bases))
    if cls_lines:
        sections.append("Class patterns:\n" + "\n".join(cls_lines))

    # Error hierarchy
    exc_classes = stats.get("exception_classes", [])
    if exc_classes:
        exc_line = f"Error hierarchy: {len(exc_classes)} exception classes"
        # Find root exceptions (those whose bases don't appear as names of other exceptions)
        exc_names = {name for name, _ in exc_classes}
        roots = [name for name, bases in exc_classes if not any(b in exc_names for b in bases)]
        subtypes = [name for name, bases in exc_classes if any(b in exc_names for b in bases)]
        if roots:
            exc_line += f", root: {', '.join(roots[:3])}"
        if subtypes:
            exc_line += f", subtypes: {', '.join(subtypes[:5])}"
            if len(subtypes) > 5:
                exc_line += f" (+{len(subtypes) - 5} more)"
        sections.append(exc_line)

    # Module organization
    sizes = stats["file_sizes"]
    if sizes:
        avg_size = sum(sizes) / len(sizes)
        sorted_sizes = sorted(sizes)
        median_size = sorted_sizes[len(sorted_sizes) // 2]
        sections.append(
            f"Module size: avg {avg_size:.0f} lines, median {median_size}"
            f" lines ({len(sizes)} files)"
        )

    # Per-directory convention divergence
    if dir_stats:
        global_type_pct = (
            stats["typed_return"] / total_fn * 100 if total_fn > 0 else 0
        )
        global_doc_pct = (
            stats["has_docstring_fn"] / total_fn * 100 if total_fn > 0 else 0
        )
        divergences: list[str] = []
        for dirname, ds in sorted(dir_stats.items()):
            dir_fn = ds.get("total_functions", 0)
            if dir_fn < 3:
                continue
            dir_type_pct = ds.get("typed_return", 0) / dir_fn * 100
            dir_doc_pct = ds.get("has_docstring_fn", 0) / dir_fn * 100
            parts = []
            if abs(dir_type_pct - global_type_pct) > 20:
                parts.append(
                    f"{dir_type_pct:.0f}% type hints"
                    f" vs {global_type_pct:.0f}% project-wide"
                )
            if abs(dir_doc_pct - global_doc_pct) > 20:
                parts.append(
                    f"{dir_doc_pct:.0f}% docstrings"
                    f" vs {global_doc_pct:.0f}% project-wide"
                )
            if parts:
                divergences.append(f"  {dirname}/: " + "; ".join(parts))
        if divergences:
            sections.append("Convention divergence:\n" + "\n".join(divergences))

    return "\n\n".join(sections) if sections else "No conventions detected."


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


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
        return f"Error: invalid edge_type '{edge_type}'. Must be one of: {', '.join(sorted(valid_edge_types))}"
    if direction not in valid_directions:
        return f"Error: invalid direction '{direction}'. Must be one of: {', '.join(sorted(valid_directions))}"

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


@mcp.tool()
def community_detection(
    min_community_size: int = 3,
    max_communities: int = 20,
) -> str:
    """Detect file communities via connected components on the import graph.

    Groups files into communities based on the undirected import graph.
    Reports community sizes and hub files (highest degree within each community).

    Args:
        min_community_size: Minimum files per community to report (default 3).
        max_communities: Maximum number of communities to return (default 20).
    """
    svc = _get_ast_service()
    idx = svc._index

    # Build undirected adjacency
    all_files: set[str] = set()
    all_files.update(idx.file_dependencies.keys())
    all_files.update(idx.file_dependents.keys())
    all_files.update(f for deps in idx.file_dependencies.values() for f in deps)

    adj: dict[str, set[str]] = {f: set() for f in all_files}
    for src, deps in idx.file_dependencies.items():
        for tgt in deps:
            adj.setdefault(src, set()).add(tgt)
            adj.setdefault(tgt, set()).add(src)

    # Connected components via BFS
    visited: set[str] = set()
    communities: list[set[str]] = []
    for start in all_files:
        if start in visited:
            continue
        component: set[str] = set()
        bfs_queue: deque[str] = deque([start])
        while bfs_queue:
            node = bfs_queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    bfs_queue.append(neighbor)
        communities.append(component)

    # Sort by size descending, filter by min size
    communities.sort(key=len, reverse=True)
    communities = [c for c in communities if len(c) >= min_community_size][:max_communities]

    lines = [f"Community detection: {len(communities)} communities (min size {min_community_size})"]
    for i, community in enumerate(communities, 1):
        lines.append(f"\n  Community {i} ({len(community)} files):")
        # Find hub file (highest degree)
        hub = max(community, key=lambda f: len(adj.get(f, set())))
        hub_degree = len(adj.get(hub, set()))
        lines.append(f"    Hub: {hub} (degree {hub_degree})")
        # Show a few sample files
        sample = sorted(community)[:5]
        for f in sample:
            degree = len(adj.get(f, set()))
            lines.append(f"    - {f} (degree {degree})")
        if len(community) > 5:
            lines.append(f"    ... and {len(community) - 5} more")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Resources: Project files and symbol lookup
# ---------------------------------------------------------------------------


@mcp.resource("attocode://project/{path}")
def project_file_resource(path: str) -> str:
    """File content with line numbers. Path-traversal protected.

    Args:
        path: Relative file path within the project.
    """
    project_dir = _get_project_dir()
    root = Path(os.path.realpath(project_dir))
    full = Path(os.path.realpath(os.path.join(project_dir, path)))
    if not full.is_relative_to(root):
        return "Error: path traversal not allowed."
    if not full.is_file():
        return f"Error: file not found: {path}"
    try:
        content = full.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        numbered = [f"{i + 1:>5} | {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.resource("attocode://symbols/{name}")
def symbol_resource(name: str) -> str:
    """Symbol definition lookup with source snippets.

    Args:
        name: Symbol name to look up.
    """
    svc = _get_ast_service()
    defs = svc.find_symbol(name)
    if not defs:
        return f"No definitions found for '{name}'."

    project_dir = _get_project_dir()
    root = Path(os.path.realpath(project_dir))

    lines = [f"Definitions for '{name}':"]
    for d in defs[:10]:
        lines.append(f"\n  {d.file_path}:{d.start_line}")
        lines.append(f"    Qualified: {d.qualified_name}")
        # Try to read source snippet (path-traversal protected)
        try:
            full = Path(os.path.realpath(os.path.join(project_dir, d.file_path)))
            if not full.is_relative_to(root):
                continue
            src_lines = full.read_text(encoding="utf-8", errors="replace").split("\n")
            start = max(0, d.start_line - 1)
            end = min(len(src_lines), d.end_line + 1)
            for i in range(start, end):
                lines.append(f"    {i + 1:>5} | {src_lines[i]}")
        except Exception:
            pass
    return "\n".join(lines)


@mcp.tool()
def relevant_context(
    files: list[str],
    depth: int = 1,
    max_tokens: int = 4000,
    include_symbols: bool = True,
) -> str:
    """Get a subgraph capsule — a file and its neighbors with symbols.

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

    center_set = set(center_rels)

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
                sym_lines.append(f"    ... and more")
            file_section.extend(sym_lines)

        section_text = "\n".join(file_section)
        section_tokens = int(len(section_text) / 3.5)

        if token_est + section_tokens > max_tokens and sections:
            sections.append(f"  ... and {len(sorted_files) - len(sections)} more files (truncated)")
            break

        sections.append(section_text)
        token_est += section_tokens

    header = (
        f"Subgraph capsule for {', '.join(center_rels)} "
        f"(depth={depth}, {len(visited)} files):\n"
    )
    return header + "\n".join(sections)


# ---------------------------------------------------------------------------
# Synthesis tools
# ---------------------------------------------------------------------------


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

    # Build sections as (header, text) pairs — drop least-critical if over budget
    # (header, text, priority) — lower priority = drop first
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
    for d, count, lines in dirs[:15]:
        pct = count / total_files * 100 if total_files else 0
        # Filter out docs/site unless significant
        if d in ("site", "docs", "doc", ".git") and pct < 10:
            continue
        dir_lines.append(f"  {d}/ — {count} files, {lines:,} lines ({pct:.0f}%)")
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
    """All-in-one codebase orientation — the best first tool call.

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
    ctx = _get_context_mgr()
    files = ctx._files

    if not files:
        return "No files discovered in this project."

    total_files = len(files)

    # Determine codebase size tier
    if total_files < 100:
        size_tier = "small"
    elif total_files < 2000:
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
        map_text = repo_map(include_symbols=True, max_tokens=int(structure_budget * 0.7))
        hs_text = hotspots(top_n=10)
        sections.append(f"## Repository Map\n{map_text}")
        sections.append(f"## Hotspots\n{hs_text}")
    else:
        # Large: hierarchical exploration + hotspots (no full map)
        explorer = _get_explorer()
        root_result = explorer.explore("", max_items=20, importance_threshold=0.3)
        explore_text = explorer.format_result(root_result)
        hs_text = hotspots(top_n=10)
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
            pass  # Graceful degradation — search is optional

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

    all_metrics = _compute_file_metrics(files, index, ast_cache)
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
def conventions(sample_size: int = 50, path: str = "") -> str:
    """Detect coding conventions and style patterns in the project.

    Analyzes function naming, type hints, docstrings, async usage,
    import style, popular decorators, class patterns, and module
    organization across a sample of the most important files.

    When ``path`` is set, only samples files within that directory subtree
    and appends a comparison to project-wide conventions. This follows
    Stripe's "scoped rules" pattern — different directories may follow
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


# ---------------------------------------------------------------------------
# LSP tools (lazy LSP manager singleton)
# ---------------------------------------------------------------------------

_lsp_manager = None


def _get_lsp_manager():
    """Lazily initialize the LSP manager for MCP server use."""
    global _lsp_manager
    if _lsp_manager is None:
        from attocode.integrations.lsp.client import LSPConfig, LSPManager

        project_dir = _get_project_dir()
        config = LSPConfig(
            enabled=True,
            root_uri=f"file://{project_dir}",
        )
        _lsp_manager = LSPManager(config=config)
    return _lsp_manager


@mcp.tool()
async def lsp_definition(file: str, line: int, col: int = 0) -> str:
    """Get the type-resolved definition location of a symbol.

    More accurate than regex cross-references — uses the language server
    for true type-resolved go-to-definition.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

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
        uri = os.path.relpath(uri, project_dir)
    except ValueError:
        pass
    return f"Definition: {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}"


@mcp.tool()
async def lsp_references(
    file: str, line: int, col: int = 0, include_declaration: bool = True,
) -> str:
    """Find all references to a symbol at position with type awareness.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
        include_declaration: Whether to include the declaration itself.
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

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
            uri = os.path.relpath(uri, project_dir)
        except ValueError:
            pass
        lines.append(f"  {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}")
    if len(locs) > 50:
        lines.append(f"  ... and {len(locs) - 50} more")
    return "\n".join(lines)


@mcp.tool()
async def lsp_hover(file: str, line: int, col: int = 0) -> str:
    """Get type signature and documentation for a symbol at position.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

    try:
        info = await lsp.get_hover(file, line, col)
    except Exception as e:
        return f"LSP not available: {e}"

    if info is None:
        return f"No hover information at {file}:{line}:{col}"
    return f"Hover at {file}:{line}:{col}:\n{info}"


@mcp.tool()
def lsp_diagnostics(file: str) -> str:
    """Get errors and warnings from the language server for a file.

    Args:
        file: File path to check for diagnostics.
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

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


# ---------------------------------------------------------------------------
# Hierarchical explorer tool
# ---------------------------------------------------------------------------

_explorer = None


def _get_explorer():
    """Lazily initialize the hierarchical explorer."""
    global _explorer
    if _explorer is None:
        from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer
        ctx = _get_context_mgr()
        ast_svc = _get_ast_service()
        _explorer = HierarchicalExplorer(ctx, ast_service=ast_svc)
    return _explorer


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
    explorer = _get_explorer()
    result = explorer.explore(
        path,
        max_items=max_items,
        importance_threshold=importance_threshold,
    )
    return explorer.format_result(result)


# ---------------------------------------------------------------------------
# Security scanning tool
# ---------------------------------------------------------------------------

_security_scanner = None


def _get_security_scanner():
    """Lazily initialize the security scanner."""
    global _security_scanner
    if _security_scanner is None:
        from attocode.integrations.security.scanner import SecurityScanner
        project_dir = _get_project_dir()
        _security_scanner = SecurityScanner(root_dir=project_dir)
    return _security_scanner


@mcp.tool()
def security_scan(
    mode: str = "full",
    path: str = "",
) -> str:
    """Scan the codebase for security issues.

    Detects hardcoded secrets, code anti-patterns, and dependency
    pinning issues. All scanning is local (no external API calls).
    Returns a compliance score (0-100) and categorized findings.

    Args:
        mode: Scan mode — 'quick' (secrets), 'full' (all), 'secrets', 'patterns', 'dependencies'.
        path: Subdirectory to scan (relative to project root, empty for all).
    """
    scanner = _get_security_scanner()
    report = scanner.scan(mode=mode, path=path)
    return scanner.format_report(report)


# ---------------------------------------------------------------------------
# Semantic search tool
# ---------------------------------------------------------------------------

_semantic_search = None
_semantic_search_lock = threading.Lock()


def _get_semantic_search():
    """Lazily initialize the semantic search manager (thread-safe)."""
    global _semantic_search
    if _semantic_search is None:
        with _semantic_search_lock:
            if _semantic_search is None:
                from attocode.integrations.context.semantic_search import SemanticSearchManager
                project_dir = _get_project_dir()
                _semantic_search = SemanticSearchManager(root_dir=project_dir)
    return _semantic_search


@mcp.tool()
def semantic_search(
    query: str,
    top_k: int = 10,
    file_filter: str = "",
) -> str:
    """Search the codebase using natural language queries.

    Finds relevant files, functions, and classes by meaning — not just
    keyword matching. Uses embeddings when available (sentence-transformers
    or OpenAI), falls back to keyword matching otherwise.

    Args:
        query: Natural language search query (e.g. "authentication middleware").
        top_k: Number of results to return (default 10).
        file_filter: Optional glob pattern to filter files (e.g. "*.py").
    """
    mgr = _get_semantic_search()
    results = mgr.search(query, top_k=top_k, file_filter=file_filter)
    return mgr.format_results(results)


# ---------------------------------------------------------------------------
# Memory / Recall tools (cross-agent learning)
# ---------------------------------------------------------------------------


_memory_store = None
_memory_store_lock = threading.Lock()


def _get_memory_store():
    """Lazily initialize and return the MemoryStore singleton (thread-safe)."""
    global _memory_store
    if _memory_store is None:
        with _memory_store_lock:
            if _memory_store is None:
                from attocode.integrations.context.memory_store import MemoryStore

                _memory_store = MemoryStore(_get_project_dir())
    return _memory_store


@mcp.tool()
def recall(query: str, scope: str = "", max_results: int = 10) -> str:
    """Retrieve relevant project learnings (patterns, conventions, gotchas).

    Call this at the start of a task or when working in unfamiliar code.
    Scope narrows results to a directory subtree (e.g. 'src/api/').

    Args:
        query: Natural language description of what you're working on.
        scope: Optional directory scope to filter learnings.
        max_results: Maximum number of learnings to return.
    """
    store = _get_memory_store()
    results = store.recall(query, scope=scope, max_results=max_results)
    if not results:
        return "No relevant learnings found for this project."

    lines = [f"## Project Learnings ({len(results)} relevant)\n"]
    for r in results:
        lines.append(f"- **[{r['type']}]** (confidence: {r['confidence']:.0%}, id: {r['id']})")
        lines.append(f"  {r['description']}")
        if r["details"]:
            lines.append(f"  _{r['details']}_")

    # Increment apply_count for returned learnings (best-effort)
    for r in results:
        try:
            store.record_applied(r["id"])
        except Exception:
            logger.debug("Failed to record_applied for learning %d", r["id"])

    return "\n".join(lines)


@mcp.tool()
def record_learning(
    type: str,  # noqa: A002
    description: str,
    details: str = "",
    scope: str = "",
    confidence: float = 0.7,
) -> str:
    """Record a project learning for future recall.

    Call this when you discover something important about the codebase:
    patterns, conventions, gotchas, workarounds, or anti-patterns.

    Args:
        type: One of 'pattern', 'antipattern', 'workaround', 'convention', 'gotcha'.
        description: Short description (1-2 sentences).
        details: Optional longer explanation or example.
        scope: Optional directory scope (e.g. 'src/api/').
        confidence: Initial confidence 0.0-1.0 (default 0.7).
    """
    store = _get_memory_store()
    try:
        learning_id = store.add(
            type=type, description=description,
            details=details, scope=scope, confidence=confidence,
        )
    except ValueError as e:
        return f"Error: {e}"
    return f"Recorded learning #{learning_id}: [{type}] {description}"


@mcp.tool()
def learning_feedback(learning_id: int, helpful: bool) -> str:
    """Mark a previously recalled learning as helpful or unhelpful.

    Call this after a recalled learning influenced your work, to improve
    future recall quality. Unhelpful learnings are eventually auto-archived.

    Args:
        learning_id: The ID from a previous recall result.
        helpful: Whether the learning was actually useful.
    """
    store = _get_memory_store()
    store.record_feedback(learning_id, helpful)
    action = "boosted" if helpful else "reduced"
    return f"Feedback recorded — confidence {action} for learning #{learning_id}."


@mcp.tool()
def list_learnings(
    status: str = "active",
    type: str = "",  # noqa: A002
    scope: str = "",
) -> str:
    """List all stored project learnings.

    Args:
        status: Filter by status: 'active' or 'archived'.
        type: Optional filter by type (pattern/antipattern/workaround/convention/gotcha).
        scope: Optional filter by directory scope.
    """
    store = _get_memory_store()
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


@mcp.resource("attocode://learnings")
def learnings_resource() -> str:
    """All active project learnings. Read this for full project knowledge base."""
    store = _get_memory_store()
    results = store.list_all(status="active")
    if not results:
        return "No project learnings recorded yet."

    lines = ["# Project Learnings\n"]
    by_type: dict[str, list[dict]] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    for type_name, entries in sorted(by_type.items()):
        lines.append(f"\n## {type_name.title()} ({len(entries)})\n")
        for r in entries:
            scope_tag = f" [{r['scope']}]" if r["scope"] else ""
            conf = f"{r['confidence']:.0%}"
            lines.append(f"- **{r['description']}**{scope_tag} (id: {r['id']}, confidence: {conf})")
            if r["details"]:
                lines.append(f"  {r['details']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification tool (explicit index update)
# ---------------------------------------------------------------------------


@mcp.tool()
def notify_file_changed(files: list[str]) -> str:
    """Notify the server that files have been modified externally.

    Call this after editing files to immediately update the AST index
    and invalidate stale semantic search embeddings. Useful when the
    file watcher is unavailable or for batch updates.

    Args:
        files: List of file paths (relative or absolute) that changed.
    """
    if not files:
        return "No files specified."

    project_dir = _get_project_dir()
    svc = _get_ast_service()
    updated = 0

    for f in files:
        try:
            p = Path(f)
            if p.is_absolute():
                rel = os.path.relpath(str(p), project_dir)
            else:
                rel = str(p)
            # Guard against path traversal
            rel = os.path.normpath(rel)
            if rel.startswith(".."):
                continue
            svc.notify_file_changed(rel)
            # Also invalidate semantic search embeddings
            try:
                smgr = _get_semantic_search()
                abs_path = os.path.join(project_dir, rel)
                smgr.invalidate_file(abs_path)
            except Exception:
                pass
            updated += 1
        except Exception as exc:
            logger.debug("notify_file_changed: error for %s: %s", f, exc)

    # Also drain the notification queue (CLI-written)
    queued = _process_notification_queue()

    total = updated + queued
    return f"Updated {total} file(s). AST index refreshed."


# ---------------------------------------------------------------------------
# Notification queue (CLI → server communication)
# ---------------------------------------------------------------------------


def _get_queue_path() -> Path:
    """Return the path to the notification queue file."""
    return Path(_get_project_dir()) / ".attocode" / "cache" / "file_changes"


_queue_lock = threading.Lock()


def _process_notification_queue() -> int:
    """Check the notification queue file and process pending changes.

    Returns number of files processed.
    """
    with _queue_lock:
        return _process_notification_queue_locked()


def _process_notification_queue_locked() -> int:
    """Inner implementation — must be called under ``_queue_lock``."""
    try:
        queue_path = _get_queue_path()
    except RuntimeError:
        return 0

    if not queue_path.exists():
        return 0

    try:
        # Atomic read-and-truncate under exclusive lock to avoid TOCTOU
        try:
            import fcntl
            with open(queue_path, "r+", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                content = fh.read()
                fh.seek(0)
                fh.truncate()
        except ImportError:
            # Windows: fall back to non-locked read+truncate
            content = queue_path.read_text(encoding="utf-8")
            queue_path.write_text("", encoding="utf-8")
    except OSError:
        return 0

    paths = [line.strip() for line in content.splitlines() if line.strip()]
    if not paths:
        return 0

    project_dir = _get_project_dir()
    svc = _get_ast_service()
    count = 0

    for rel in paths:
        # Guard against path traversal (e.g. ../../etc/passwd)
        norm = os.path.normpath(rel)
        if norm.startswith(".."):
            continue
        try:
            svc.notify_file_changed(norm)
            try:
                smgr = _get_semantic_search()
                abs_path = os.path.join(project_dir, norm)
                smgr.invalidate_file(abs_path)
            except Exception:
                pass
            count += 1
        except Exception:
            pass

    if count:
        logger.debug("Processed %d queued file notification(s)", count)
    return count


_queue_thread: threading.Thread | None = None


def _start_queue_poller(project_dir: str) -> None:
    """Start a background thread that polls the notification queue every 2s."""
    global _queue_thread

    if _queue_thread is not None:
        return

    def _poll_loop() -> None:
        while not _watcher_stop.is_set():
            try:
                _process_notification_queue()
            except Exception:
                pass
            _watcher_stop.wait(2.0)

    _queue_thread = threading.Thread(
        target=_poll_loop, daemon=True, name="code-intel-queue-poller"
    )
    _queue_thread.start()
    logger.debug("Notification queue poller started")


# ---------------------------------------------------------------------------
# File watcher (background thread)
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
}

_watcher_thread: threading.Thread | None = None
_watcher_stop = threading.Event()


def _start_file_watcher(project_dir: str) -> None:
    """Start a background file watcher that updates the AST index on changes.

    Uses watchfiles (Rust-backed, ~200ms debounce) if available, otherwise
    skips silently. Calls ASTService.notify_file_changed() for modified code files.
    """
    global _watcher_thread

    if _watcher_thread is not None:
        return  # Already running

    try:
        from watchfiles import watch, Change
    except ImportError:
        logger.debug("watchfiles not installed — file watcher disabled")
        return

    def _watcher_loop() -> None:
        try:
            for changes in watch(
                project_dir,
                stop_event=_watcher_stop,
                recursive=True,
                # Ignore hidden dirs, node_modules, __pycache__, .git
                watch_filter=lambda _, path: (
                    not any(
                        part.startswith(".") or part in ("node_modules", "__pycache__", ".git")
                        for part in Path(path).parts
                    )
                    and Path(path).suffix.lower() in _CODE_EXTENSIONS
                ),
            ):
                if _watcher_stop.is_set():
                    break

                svc = _get_ast_service()
                for change_type, path_str in changes:
                    if change_type in (Change.modified, Change.added, Change.deleted):
                        try:
                            rel = os.path.relpath(path_str, project_dir)
                            svc.notify_file_changed(rel)
                            # Also invalidate semantic search embeddings
                            try:
                                smgr = _get_semantic_search()
                                smgr.invalidate_file(path_str)
                            except Exception:
                                pass
                            logger.debug("File watcher: updated %s", rel)
                        except Exception:
                            pass  # Best-effort — don't crash the watcher
        except Exception:
            logger.debug("File watcher stopped", exc_info=True)

    _watcher_thread = threading.Thread(
        target=_watcher_loop, daemon=True, name="code-intel-watcher"
    )
    _watcher_thread.start()
    logger.info("File watcher started for %s", project_dir)


def _stop_file_watcher() -> None:
    """Stop the background file watcher and queue poller."""
    global _watcher_thread, _queue_thread
    _watcher_stop.set()
    for t in (_watcher_thread, _queue_thread):
        if t is not None:
            t.join(timeout=2.0)
    _watcher_thread = None
    _queue_thread = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# Subcommands that should be dispatched to the CLI handler instead of
# starting the MCP server.
_CLI_SUBCOMMANDS = {"install", "uninstall", "serve", "status", "notify", "help", "--help", "-h"}


def main() -> None:
    """CLI entry point for the MCP server.

    If the first positional argument is a known subcommand (install, uninstall,
    notify, status, serve, help), delegates to ``cli.dispatch_code_intel``.
    Otherwise starts the MCP server on stdio.
    """
    args = sys.argv[1:]

    # Detect subcommands — delegate to CLI dispatcher
    if args and args[0] in _CLI_SUBCOMMANDS:
        from attocode.code_intel.cli import dispatch_code_intel

        dispatch_code_intel(args)
        return

    # No subcommand — start MCP server
    project_dir = "."
    transport = "stdio"
    host = "127.0.0.1"
    port = 8080
    for i, arg in enumerate(args):
        if arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
        elif arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
        elif arg == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
        elif arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])

    project_dir = os.path.abspath(project_dir)
    os.environ["ATTOCODE_PROJECT_DIR"] = project_dir

    # Start file watcher and notification queue poller in background
    _start_file_watcher(project_dir)
    _start_queue_poller(project_dir)

    logger.info("Starting attocode-code-intel for %s (transport=%s)", project_dir, transport)
    try:
        if transport == "http":
            from attocode.code_intel.cli import _serve_http

            _serve_http(project_dir, host=host, port=port, debug=False)
        elif transport == "sse":
            mcp.run(transport="sse", host=host, port=port)
        else:
            mcp.run(transport="stdio")
    finally:
        _stop_file_watcher()


if __name__ == "__main__":
    main()
