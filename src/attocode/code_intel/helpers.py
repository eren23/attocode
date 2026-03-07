"""Synthesis helpers for the code-intel MCP server.

Contains data classes, constants, and pure-logic helpers used by
multiple tool modules.  Extracted from server.py for maintainability.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


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
