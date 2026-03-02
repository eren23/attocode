"""MCP server exposing Attocode's code intelligence capabilities.

Provides 11 tools for deep codebase understanding:
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
- conventions: Code style and convention detection

Usage::

    attocode-code-intel --project /path/to/repo
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

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
    queue_fwd: list[tuple[str, int]] = [(rel, 0)]
    while queue_fwd:
        current, d = queue_fwd.pop(0)
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
    queue_rev: list[tuple[str, int]] = [(rel, 0)]
    while queue_rev:
        current, d = queue_rev.pop(0)
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
def conventions(sample_size: int = 50) -> str:
    """Detect coding conventions and style patterns in the project.

    Analyzes function naming, type hints, docstrings, async usage,
    import style, popular decorators, class patterns, and module
    organization across a sample of the most important files.

    Args:
        sample_size: Number of files to sample (default 50).
    """
    svc = _get_ast_service()
    ast_cache = svc._ast_cache

    if not ast_cache:
        return "No files parsed — cannot detect conventions."

    ctx = _get_context_mgr()
    files = ctx._files

    # Sample top files by importance that exist in AST cache
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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the MCP server."""
    # Parse --project from sys.argv
    project_dir = "."
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
            break
        if arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
            break

    os.environ["ATTOCODE_PROJECT_DIR"] = os.path.abspath(project_dir)

    logger.info("Starting attocode-code-intel for %s", project_dir)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
