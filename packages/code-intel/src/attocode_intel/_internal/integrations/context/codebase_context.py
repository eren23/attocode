"""Codebase context system.

Provides intelligent code understanding through:
- File discovery with ignore patterns
- Repository map generation
- Lightweight tree view
- File importance scoring
- Context selection for prompts
"""

from __future__ import annotations

import os
import posixpath
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attocode_intel._internal.integrations.utilities.ignore import DEFAULT_IGNORES
from attocode_intel._internal.integrations.utilities.token_estimate import CHARS_PER_TOKEN

from .language_registry import LANG_EXTENSIONS

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(slots=True)
class FileInfo:
    """Information about a discovered file."""

    path: str
    relative_path: str
    size: int = 0
    language: str = ""
    importance: float = 0.0
    is_test: bool = False
    is_config: bool = False
    line_count: int = 0

    @property
    def extension(self) -> str:
        return Path(self.path).suffix


@dataclass(slots=True)
class RepoMap:
    """Repository map showing file structure and key definitions."""

    tree: str  # Text tree view
    files: list[FileInfo]
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    symbols: dict[str, list[str]] = field(default_factory=dict)  # rel_path -> symbol names


@dataclass(slots=True)
class DependencyGraph:
    """Forward and reverse dependency graph between files."""

    forward: dict[str, set[str]] = field(default_factory=dict)  # file -> files it imports
    reverse: dict[str, set[str]] = field(default_factory=dict)  # file -> files that import it

    unresolved: dict[str, list[str]] = field(default_factory=dict)

    def add_edge(self, source: str, target: str) -> None:
        """Add a dependency edge: source imports target."""
        self.forward.setdefault(source, set()).add(target)
        self.reverse.setdefault(target, set()).add(source)

    def get_importers(self, file_path: str) -> set[str]:
        """Get files that import the given file."""
        return self.reverse.get(file_path, set())

    def get_imports(self, file_path: str) -> set[str]:
        """Get files that the given file imports."""
        return self.forward.get(file_path, set())

    def hub_score(self, file_path: str) -> float:
        """Score based on how many files depend on this file (0.0-0.2)."""
        count = len(self.reverse.get(file_path, set()))
        return min(0.2, count * 0.04)

    def pagerank(
        self,
        damping: float = 0.85,
        iterations: int = 20,
        tolerance: float = 1e-6,
    ) -> dict[str, float]:
        """Compute PageRank scores for all files in the dependency graph.

        Uses the reverse (importer) graph: a file is important if important
        files import it. Returns scores normalized to 0.0-1.0 range.

        Args:
            damping: Damping factor (probability of following a link). Default 0.85.
            iterations: Maximum power-iteration rounds. Default 20.
            tolerance: Early-stop when max score change < tolerance.

        Returns:
            Dict mapping file paths to PageRank scores (0.0-1.0 normalized).
        """
        # Collect all nodes from both forward and reverse graphs
        all_nodes: set[str] = set()
        all_nodes.update(self.forward.keys())
        all_nodes.update(self.reverse.keys())
        for targets in self.forward.values():
            all_nodes.update(targets)
        for sources in self.reverse.values():
            all_nodes.update(sources)

        if not all_nodes:
            return {}

        n = len(all_nodes)
        base = 1.0 / n
        scores: dict[str, float] = {node: base for node in all_nodes}

        # Pre-compute out-degree (forward edges = this file imports N others)
        out_degree: dict[str, int] = {}
        for node in all_nodes:
            out_degree[node] = len(self.forward.get(node, set()))

        for _ in range(iterations):
            new_scores: dict[str, float] = {}
            for node in all_nodes:
                # Sum contributions from files that import this node
                rank_sum = 0.0
                for importer in self.reverse.get(node, set()):
                    od = out_degree.get(importer, 0)
                    if od > 0:
                        rank_sum += scores[importer] / od
                new_scores[node] = (1 - damping) / n + damping * rank_sum

            # Check convergence
            max_diff = max(
                abs(new_scores[node] - scores[node]) for node in all_nodes
            )
            scores = new_scores
            if max_diff < tolerance:
                break

        # Normalize to 0.0-1.0
        max_score = max(scores.values()) if scores else 1.0
        if max_score > 0:
            scores = {k: v / max_score for k, v in scores.items()}

        return scores

    def to_import_graph(self) -> dict[str, list[str]]:
        """Convert to the dict format expected by CodeSelector.ranked_search."""
        return {k: list(v) for k, v in self.forward.items()}


# Language detection by extension

EXTENSION_LANGUAGES: dict[str, str] = {
    **LANG_EXTENSIONS, ".md": "markdown", ".sql": "sql", ".dockerfile": "docker",
}

# Patterns indicating test files
TEST_PATTERNS = (
    "test_", "_test.", ".test.", "tests/", "test/",
    "spec_", "_spec.", ".spec.", "specs/", "spec/",
    "__tests__/",
)

# Patterns indicating config files
CONFIG_PATTERNS = (
    "config.", ".config.", "settings.",
    "pyproject.toml", "package.json", "tsconfig",
    ".eslintrc", ".prettierrc", "Makefile", "Dockerfile",
    ".github/", ".gitlab-ci",
)

# File extensions to skip (non-source, binary, generated)
SKIP_EXTENSIONS = {
    # Compiled / bytecode
    ".pyc", ".pyo", ".class", ".o", ".obj", ".so", ".dylib", ".dll",
    ".a", ".lib", ".exe", ".wasm",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z", ".jar", ".war",
    # Media
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Data / DB
    ".db", ".sqlite", ".sqlite3",
    ".parquet", ".feather", ".hdf5", ".h5",
    # Lock files (large, generated)
    ".lock",
    # Maps
    ".map",
    # Certificates
    ".pem", ".crt", ".key", ".p12",
}

# Filenames to skip (exact match)
SKIP_FILENAMES = {
    ".DS_Store", "Thumbs.db", ".gitkeep", ".npmrc",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "uv.lock",
    "composer.lock", "Gemfile.lock", "Cargo.lock",
    "go.sum",
}


def _detect_source_prefixes(root_dir: str) -> list[str]:
    """Detect source directory prefixes for import resolution.

    Many Python projects use a ``src/`` layout where packages live under
    ``src/`` (e.g., ``src/mypackage/``).  When files are discovered with
    relative paths like ``src/mypackage/foo.py``, absolute imports such as
    ``from mypackage.foo import ...`` fail because the resolver generates
    candidate ``mypackage/foo.py`` which doesn't match the ``src/``-prefixed
    key in the file index.

    This function detects such prefixes by examining:
    1. ``pyproject.toml`` — hatchling ``packages`` or setuptools ``package-dir``
    2. ``setup.cfg`` — ``[options] package_dir``
    3. Filesystem fallback — ``src/`` containing Python packages

    Returns:
        Sorted list of prefix strings ending with ``/`` (e.g., ``["src/"]``).
    """
    prefixes: set[str] = set()
    root = Path(root_dir)

    # --- pyproject.toml ---
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        import tomllib  # stdlib, Python 3.11+ (project requires 3.12+)

        try:
            with open(pyproject, "rb") as fh:
                data = tomllib.load(fh)

            # Hatchling: [tool.hatch.build.targets.wheel] packages = ["src/pkg"]
            hatch_packages = (
                data.get("tool", {})
                .get("hatch", {})
                .get("build", {})
                .get("targets", {})
                .get("wheel", {})
                .get("packages", [])
            )
            for pkg in hatch_packages:
                if len(Path(pkg).parts) >= 2:
                    prefixes.add(Path(pkg).parent.as_posix() + "/")

            # Setuptools: [tool.setuptools] package-dir = {"" = "src"}
            setup_pkg_dir = (
                data.get("tool", {})
                .get("setuptools", {})
                .get("package-dir", {})
            )
            for _key, src_dir in setup_pkg_dir.items():
                if src_dir:
                    prefixes.add(src_dir.rstrip("/") + "/")
        except Exception:
            pass

    # --- setup.cfg ---
    if not prefixes:
        setup_cfg = root / "setup.cfg"
        if setup_cfg.exists():
            try:
                import configparser

                cfg = configparser.ConfigParser()
                cfg.read(str(setup_cfg))
                pkg_dir = cfg.get("options", "package_dir", fallback="")
                if "=" in pkg_dir:
                    src_dir = pkg_dir.split("=", 1)[1].strip()
                    if src_dir:
                        prefixes.add(src_dir.rstrip("/") + "/")
            except Exception:
                pass

    # --- Filesystem fallback ---
    if not prefixes:
        src_dir_path = root / "src"
        if src_dir_path.is_dir():
            for child in src_dir_path.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    prefixes.add("src/")
                    break

    return sorted(prefixes)


def _build_file_index(
    files: list[FileInfo],
    root_dir: str,
    ast_cache: dict | None = None,
) -> dict[str, str]:
    """Build a file index mapping normalized paths to relative paths.

    In addition to the standard ``relative_path`` keys, this function
    adds prefix-stripped alternate keys for projects using a ``src/``
    layout (or similar).  For example, if the index contains
    ``src/attocode/core/loop.py``, an alternate key
    ``attocode/core/loop.py`` is also added so that
    ``_resolve_python_import`` can find it when resolving
    ``from attocode.core.loop import ...``.

    Args:
        files: Discovered files with relative paths.
        root_dir: Repository root directory.

    Returns:
        Mapping of normalized paths (with ``/``) to relative paths.
    """
    from .module_resolution import FileIndex
    file_index = FileIndex()
    for f in files:
        normalized = f.relative_path.replace(os.sep, "/")
        file_index[normalized] = f.relative_path

    # Detect source prefixes and add stripped alternate keys.
    source_prefixes = set(_detect_source_prefixes(root_dir)) | _python_import_roots(file_index)
    if source_prefixes:
        _add_root_keys(file_index, source_prefixes)

    file_index.configure_javascript(root_dir)
    file_index.configure_go(root_dir)
    file_index.configure_rust(root_dir)
    file_index.configure_namespaces(ast_cache or {})
    file_index.configure_native_includes(root_dir)
    file_index.configure_swift(root_dir)
    return file_index


def _python_import_roots(paths) -> set[str]:
    """Folders that hold a top-level Python package, as ``lib/`` for ``lib/pkg/__init__.py``.

    Such a folder is an import root: src/, packages/<name>/src/ of a monorepo,
    lib/ of matplotlib or python/ of ray.
    """
    roots: set[str] = set()
    for path in paths:
        package, _, name = path.rpartition("/")
        parent = package.rpartition("/")[0]
        if name == "__init__.py" and parent and parent + "/__init__.py" not in paths:
            roots.add(parent + "/")
    return roots


def _add_root_keys(file_index: dict[str, str], roots: set[str]) -> None:
    """Add a key without the root prefix for each file below an import root."""
    extra: dict[str, str] = {}
    ambiguous: set[str] = set()
    for normalized, rel_path in file_index.items():
        parts = normalized.split("/")
        # Shallow roots first, so a deeper root wins, as in sorted prefix order.
        for depth in range(1, len(parts)):
            prefix = "/".join(parts[:depth]) + "/"
            stripped = normalized[len(prefix):]
            # Don't override direct matches
            if prefix in roots and stripped not in file_index:
                if stripped in extra and extra[stripped] != rel_path:
                    ambiguous.add(stripped)
                extra[stripped] = rel_path
    file_index.update({key: value for key, value in extra.items() if key not in ambiguous})


def python_module_index(paths) -> dict[str, str]:
    """Module-path keys for ``_resolve_python_import`` from repository paths alone."""
    file_index = {path: path for path in paths}
    _add_root_keys(file_index, _python_import_roots(file_index))
    return file_index


def _resolve_python_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a Python import module name to a relative file path.

    Args:
        module: Module name (e.g. 'os', 'mypackage.utils', '.sibling').
        source_file: Relative path of the importing file.
        file_index: Mapping of relative paths (normalized with /) to relative paths.

    Returns:
        Resolved relative path or None if not found.
    """
    # Skip stdlib / third-party (no dots in path and not found locally)
    parts = module.split(".")

    # Handle relative imports (leading dots)
    if module.startswith("."):
        # Strip leading dots and compute base directory
        dots = len(module) - len(module.lstrip("."))
        base = Path(source_file).parent
        for _ in range(dots - 1):
            base = base.parent
        parts = [p for p in module.lstrip(".").split(".") if p]
        candidate = str(base / "/".join(parts)) if parts else str(base / "__init__")
    else:
        candidate = "/".join(parts)

    # Try candidate.py, candidate/__init__.py
    for suffix in (".py", "/__init__.py"):
        key = candidate + suffix
        normalized = key.replace(os.sep, "/")
        if normalized in file_index:
            return file_index[normalized]

    return None


def _resolve_js_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a JS/TS import path to a relative file path.

    Args:
        module: Import path (e.g. './utils', '../lib/helpers').
        source_file: Relative path of the importing file.
        file_index: Mapping of relative paths (normalized with /) to relative paths.

    Returns:
        Resolved relative path or None if not found.
    """
    if module.startswith("."):
        candidates = [os.path.normpath(str(Path(source_file).parent / module))]
    elif hasattr(file_index, "javascript_candidates"):
        candidates = list(file_index.javascript_candidates(module, source_file))
    else:
        return None
    for resolved in candidates:
        # TS resolves source .ts files behind emitted .js imports.
        variants = [resolved]
        if resolved.endswith((".js", ".jsx", ".mjs", ".cjs")):
            variants += [str(Path(resolved).with_suffix(ext)) for ext in (".ts", ".tsx", ".mts", ".cts")]
        for candidate in variants:
            for suffix in ("", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json", "/index.ts", "/index.tsx", "/index.js", "/index.cjs", "/index.mjs"):
                key = os.path.normpath(candidate + suffix).replace(os.sep, "/")
                if key in file_index:
                    return file_index[key]
    return None


def _resolve_rust_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve local Rust modules, including nested workspace crate roots.

    External dependencies and ambiguous matches remain unresolved.
    """
    if not module or module.startswith(("std::", "core::", "alloc::", "extern ")):
        return None
    if hasattr(file_index, "rust_dependency_entry") and "::" in module:
        alias, rest = module.split("::", 1)
        entry = file_index.rust_dependency_entry(alias, source_file)
        if entry:
            base = Path(entry).parent
            parts = rest.split("::")
            for length in range(len(parts), 0, -1):
                candidate = str(base.joinpath(*parts[:length]))
                for suffix in (".rs", "/mod.rs"):
                    key = os.path.normpath(candidate + suffix).replace(os.sep, "/")
                    if key in file_index:
                        return file_index[key]
            return entry
    source = Path(source_file)
    roots = [parent for parent in (source.parent, *source.parents)
             if any(str(parent / entry) in file_index for entry in ("lib.rs", "main.rs"))]
    crate_root = roots[0] if roots else Path("src")
    current = source.parent if source.stem in {"lib", "main", "mod"} else source.with_suffix("")
    if module.startswith("mod:"):
        parts = [module[4:]]
        base = current
    else:
        parts = module.split("::")
        if parts[0] == "crate":
            base, parts = crate_root, parts[1:]
        elif parts[0] == "self":
            base, parts = current, parts[1:]
        elif parts[0] == "super":
            base = current
            while parts and parts[0] == "super":
                base, parts = base.parent, parts[1:]
        else:
            # Rust 2015 crate-relative paths, then workspace crate source roots.
            base = crate_root
            if len(parts) > 1:
                name = parts[0].replace("_", "-")
                candidates = {str(Path(f).parent) for f in file_index.values()
                              if Path(f).name == "lib.rs" and name in Path(f).parts}
                if len(candidates) == 1:
                    base, parts = Path(candidates.pop()), parts[1:]
    for length in range(len(parts), 0, -1):
        candidate = str(base.joinpath(*parts[:length]))
        for suffix in (".rs", "/mod.rs"):
            key = os.path.normpath(candidate + suffix).replace(os.sep, "/")
            if key in file_index:
                return file_index[key]
    # Root-level reexports live in the crate entrypoint, not a same-named file.
    if len(parts) == 1 and not module.startswith("mod:"):
        for entry in ("lib.rs", "main.rs"):
            key = str(base / entry)
            if key in file_index:
                return file_index[key]
    return None


def _resolve_go_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Compatibility single-target view; package imports can have several files."""
    candidates = file_index.go_candidates(module, source_file) if hasattr(file_index, "go_candidates") else []
    if not hasattr(file_index, "go_candidates") and module.startswith(("./", "../")):
        directory = os.path.normpath(str(Path(source_file).parent / module)).replace(os.sep, "/")
        if directory != ".." and not directory.startswith("../"):
            candidates = sorted({value for key, value in file_index.items()
                                 if str(Path(key).parent) == directory
                                 and key.endswith(".go") and not key.endswith("_test.go")})
    return candidates[0] if len(candidates) == 1 else None


def resolve_import_targets(language, module, source_file, file_index, *, include_system=False):
    """All local files supported by an import, never an arbitrary first match."""
    if language in {"c", "cpp"} and hasattr(file_index, "c_candidates"):
        return file_index.c_candidates(module, source_file, system=include_system)
    if language == "swift" and hasattr(file_index, "swift_candidates"):
        return file_index.swift_candidates(module, source_file)
    if language in {"java", "csharp", "kotlin", "scala", "php", "elixir"} and hasattr(file_index, "namespace_candidates"):
        return file_index.namespace_candidates(language, module)
    if language == "go" and hasattr(file_index, "go_candidates"):
        return file_index.go_candidates(module, source_file)
    if language in {"ocaml", "perl", "crystal"}:
        return _optional_import_targets(language, module, source_file, file_index)
    resolver = IMPORT_RESOLVERS.get(language)
    target = resolver(module, source_file, file_index) if resolver else None
    return [target] if target else []


def _resolve_java_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a Java import to a relative file path.

    Handles:
    - ``import com.myproject.utils.Helper`` → ``com/myproject/utils/Helper.java``
    - Skips stdlib (``java.``, ``javax.``) and common third-party packages
    """
    if not module:
        return None

    # Skip stdlib and common external packages
    if module.startswith(("java.", "javax.", "sun.", "com.sun.")):
        return None

    # Skip wildcard imports for resolution (still tracked for other purposes)
    if module.endswith(".*"):
        module = module[:-2]

    # Convert package.Class to path
    candidate = module.replace(".", "/") + ".java"
    normalized = candidate.replace(os.sep, "/")
    if normalized in file_index:
        return file_index[normalized]

    # Try under common source roots
    for prefix in ("src/main/java/", "src/", "app/src/main/java/"):
        key = prefix + normalized
        if key in file_index:
            return file_index[key]

    return None


def _resolve_ruby_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a Ruby require/require_relative to a relative file path.

    Handles:
    - ``require_relative './helper'`` → relative path resolution
    - ``require 'mylib/utils'`` → try local lib/ resolution
    - Skips stdlib/gems (no reliable local resolution)
    """
    if not module:
        return None

    # require_relative: module starts with ./ or ../
    if module.startswith("./") or module.startswith("../"):
        base = Path(source_file).parent
        resolved = os.path.normpath(str(base / module)).replace(os.sep, "/")
        for suffix in ("", ".rb"):
            key = resolved + suffix
            if key in file_index:
                return file_index[key]
        return None

    # Plain require: try as a local path with .rb extension
    candidate = module
    for suffix in (".rb",):
        key = candidate + suffix
        normalized = key.replace(os.sep, "/")
        if normalized in file_index:
            return file_index[normalized]
        # Try under lib/
        lib_key = "lib/" + normalized
        if lib_key in file_index:
            return file_index[lib_key]

    return None


def _resolve_c_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a C/C++ #include to a relative file path.

    Handles:
    - ``#include "myheader.h"`` → search in same dir and include paths
    - Skips system headers (angle-bracket includes like ``<stdio.h>``)

    Note: The module string from the parser is the include path without
    quotes/brackets. System includes are identified by convention (no path
    separators, common system headers).
    """
    if not module:
        return None

    # System headers (angle-bracket includes are typically marked differently,
    # but as a heuristic: skip common system/stdlib headers)
    _SYSTEM_PREFIXES = (  # noqa: N806
        "stdio", "stdlib", "string", "math", "time", "errno", "signal",
        "assert", "ctype", "locale", "setjmp", "stdarg", "stddef",
        "sys/", "linux/", "windows.h", "unistd.h", "fcntl.h",
        "iostream", "vector", "map", "string", "algorithm", "memory",
        "functional", "utility", "numeric", "iterator", "cassert",
        "cstdio", "cstdlib", "cstring", "cmath",
    )
    module_lower = module.lower()
    if any(module_lower.startswith(p) or module_lower == p for p in _SYSTEM_PREFIXES):
        return None

    # Try exact path in file index
    normalized = module.replace(os.sep, "/")
    if normalized in file_index:
        return file_index[normalized]

    # Try relative to source file directory
    source_dir = str(Path(source_file).parent)
    candidate = source_dir + "/" + normalized
    if candidate in file_index:
        return file_index[candidate]

    # Try common include directories
    for prefix in ("include/", "src/", "inc/"):
        key = prefix + normalized
        if key in file_index:
            return file_index[key]

    return None


def _resolve_literal_import(language, module, source_file, file_index):
    if not module:
        return None
    if language == "zig":
        keys = [os.path.normpath(str(Path(source_file).parent / module))] if module.endswith(".zig") else []
    elif language == "lua":
        base = module.replace(".", "/")
        keys = [base + ".lua", base + "/init.lua"]
    else:  # Shell source paths depend on cwd; do not choose between local candidates.
        keys = [os.path.normpath(module), os.path.normpath(str(Path(source_file).parent / module))]
    targets = {file_index[key] for key in keys if key in file_index and not key.startswith("../")}
    return next(iter(targets)) if len(targets) == 1 else None


def _resolve_namespace_import(language, module, source_file, file_index):
    candidates = file_index.namespace_candidates(language, module) if hasattr(file_index, "namespace_candidates") else []
    return candidates[0] if len(candidates) == 1 else None


def _optional_import_targets(language, module, source_file, file_index):
    """Conservative static workspace candidates, never compiler/load-path proof."""
    if not isinstance(module, str) or not module or any(c in module for c in "\x00\r\n\\"):
        return []
    source = source_file.replace("\\", "/")
    if source.startswith("/") or posixpath.normpath(source).startswith("../"):
        return []
    directory = posixpath.dirname(source)
    groups = []
    if language == "ocaml":
        parts = module.split(".")
        if not all(p.isidentifier() and p[0].isupper() for p in parts):
            return []
        name = parts[0]
        stems = {name, name[0].lower() + name[1:]}
        for root in {"", directory}:
            for stem in stems:
                groups.append({posixpath.join(root, stem + suffix) for suffix in (".ml", ".mli")})
    elif language == "perl":
        parts = module.split("::")
        if not all(p.isidentifier() for p in parts):
            return []
        name = "/".join(parts) + ".pm"
        groups = [{name}, {"lib/" + name}]
    elif language == "crystal":
        if not module.startswith(("./", "../")) or any(c in module for c in '*?[]#"\'`') or module.endswith('/'):
            return []
        name = posixpath.normpath(posixpath.join(directory, module))
        if name in {".", ".."} or name.startswith(("/", "../")):
            return []
        groups = [{name if name.endswith(".cr") else name + ".cr"}]
    # A module can have an implementation and interface, but competing source
    # roots or filename casings are ambiguous. Do not pick the first match.
    matches = {tuple(sorted({file_index[key] for key in group if key in file_index})) for group in groups}
    matches.discard(())
    return list(next(iter(matches))) if len(matches) == 1 else []


def _optional_import_target(language, module, source_file, file_index):
    targets = _optional_import_targets(language, module, source_file, file_index)
    return targets[0] if len(targets) == 1 else None


IMPORT_RESOLVERS = {
    **{language: partial(_optional_import_target, language) for language in ("ocaml", "perl", "crystal")},
    "python": _resolve_python_import, "javascript": _resolve_js_import,
    "typescript": _resolve_js_import, "rust": _resolve_rust_import,
    "go": _resolve_go_import, "java": _resolve_java_import,
    **{language: partial(_resolve_namespace_import, language) for language in ("csharp", "php", "kotlin", "scala", "elixir", "swift")},
    **{language: partial(_resolve_literal_import, language) for language in ("lua", "bash", "zig")},
    "ruby": _resolve_ruby_import, "c": _resolve_c_import, "cpp": _resolve_c_import,
}


def _compute_dynamic_cap(files: list[FileInfo], configured_max: int) -> int:
    """Compute a dynamic file cap based on repo composition.

    Rules:
    - <1,000 source files → no cap (keep all)
    - 1,000–5,000 source files → cap at source count (keep all source, trim non-source)
    - 5,000–20,000 → cap at 10,000
    - 20,000+ → cap at 20,000

    Args:
        files: All discovered files (before truncation).
        configured_max: The user-configured max_files (used as a minimum).

    Returns:
        The effective cap to apply.
    """
    source_count = sum(1 for f in files if f.language)
    total = len(files)

    if source_count < 1_000:
        cap = total  # Keep everything
    elif source_count <= 5_000:
        cap = max(source_count, configured_max)
    elif source_count <= 20_000:
        cap = max(10_000, configured_max)
    else:
        cap = max(20_000, configured_max)

    return cap


def build_dependency_graph(
    files: list[FileInfo],
    root_dir: str,
    *,
    ast_cache: dict | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> DependencyGraph:
    """Build a dependency graph from file imports.

    Parses each file's imports and resolves them to file paths
    to build forward (imports) and reverse (imported-by) graphs.

    Args:
        files: Discovered files with language info.
        root_dir: Repository root directory.

    Returns:
        DependencyGraph with forward and reverse edges.
    """
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file

    graph = DependencyGraph()

    # Namespace imports require declaration evidence, not a directory suffix.
    # Reuse already parsed files and parse each missing namespace file once.
    cached = dict(ast_cache or {})
    for f in files:
        if f.language in {"java", "csharp", "kotlin", "scala", "php", "go", "elixir"} and f.relative_path not in cached:
            if check_cancelled is not None:
                check_cancelled()
            try:
                cached[f.relative_path] = parse_file(f.path)
            except (OSError, ValueError):
                continue
    file_index = _build_file_index(files, root_dir, cached)

    # Languages that have parseable imports
    supported_langs = set(IMPORT_RESOLVERS)

    for f in files:
        if check_cancelled is not None:
            check_cancelled()
        if f.language not in supported_langs:
            continue

        try:
            ast = cached.get(f.relative_path)
            if ast is None:
                ast = parse_file(f.path)
        except Exception:
            continue

        for imp in ast.imports:
            if check_cancelled is not None:
                check_cancelled()
            targets = resolve_import_targets(f.language, imp.module, f.relative_path, file_index, include_system=imp.include_system)
            for target in targets:
                if target != f.relative_path:
                    graph.add_edge(f.relative_path, target)
            if not targets:
                graph.unresolved.setdefault(f.relative_path, []).append(imp.module)

    return graph


@dataclass
class CodebaseContextManager:
    """Manages codebase context for intelligent code understanding.

    Discovers files, builds repository maps, scores importance,
    and selects relevant context for LLM prompts.

    Supports incremental updates: after file edits, call
    ``mark_file_dirty()`` then ``update_dirty_files()`` to
    re-parse only changed files instead of a full ``discover_files()``.
    """

    root_dir: str
    max_files: int = 2000
    max_context_tokens: int = 8000
    discovered_file_count: int = 0
    discovery_truncated: bool = False
    excluded_checkout_roots: list[str] = field(default_factory=list)
    excluded_checkout_roots_truncated: bool = False
    ignore_patterns: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORES))
    _files: list[FileInfo] = field(default_factory=list, repr=False)
    _repo_map: RepoMap | None = field(default=None, repr=False)
    _dep_graph: DependencyGraph | None = field(default=None, repr=False)
    _file_mtimes: dict[str, float] = field(default_factory=dict, repr=False)
    _dirty_files: set[str] = field(default_factory=set, repr=False)
    _ast_cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _last_refresh_time: float = field(default=0.0, repr=False)
    _staleness_threshold: float = field(default=300.0, repr=False)  # 5 minutes
    _ignored_checkout_dirs: list[str] = field(default_factory=list, repr=False)
    _ignored_checkout_dirs_capped: bool = field(default=False, repr=False)
    cancelled: Callable[[], bool] | None = field(default=None, repr=False, compare=False)
    _discovery_snapshot: Any = field(default=None, repr=False, compare=False)

    def _check_cancelled(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise InterruptedError("File discovery cancelled")

    @property
    def is_stale(self) -> bool:
        """Check if the file discovery cache is older than the staleness threshold."""
        if not self._files or self._last_refresh_time == 0.0:
            return True
        return (time.monotonic() - self._last_refresh_time) > self._staleness_threshold

    def _ensure_fresh(self) -> None:
        """Auto-refresh if the cache is stale."""
        if self.is_stale:
            self.discover_files()

    def refresh_excluded_checkout_roots(self) -> None:
        """Refresh bounded checkout guidance without rediscovering source files."""
        root = Path(self.root_dir)
        self.excluded_checkout_roots = []
        self.excluded_checkout_roots_truncated = self._ignored_checkout_dirs_capped
        for rel_path in self._ignored_checkout_dirs:
            path = root / rel_path
            if path.is_symlink() or not path.is_dir():
                continue
            candidates = [(path, rel_path)]
            try:
                with os.scandir(path) as entries:
                    for offset, entry in enumerate(entries):
                        if offset >= 128:
                            self.excluded_checkout_roots_truncated = True
                            break
                        if entry.is_dir(follow_symlinks=False):
                            candidates.append((Path(entry.path), f"{rel_path}/{entry.name}"))
            except OSError:
                self.excluded_checkout_roots_truncated = True
                continue
            for candidate, relative in candidates:
                if (candidate / ".git").exists():
                    if len(self.excluded_checkout_roots) < 5:
                        self.excluded_checkout_roots.append(relative.replace(os.sep, "/"))
                    else:
                        self.excluded_checkout_roots_truncated = True
        self.excluded_checkout_roots.sort()

    def reuse_discovery(self, snapshot) -> bool:
        """Adopt a validated inventory with this consumer's cap, without shared mutation.

        The donor publishes only complete, untruncated discoveries. Every relevant
        directory/file and the ignore-file identity must still match. A failed
        validation leaves this context empty so its normal fresh discovery runs.
        """
        if snapshot is None or not snapshot.valid_for(self):
            return False
        files = [FileInfo(*row) for row in snapshot.files]
        cap = _compute_dynamic_cap(files, self.max_files)
        self.discovered_file_count = len(files)
        self.discovery_truncated = len(files) > cap
        self._files = files[:cap]
        self._last_refresh_time = snapshot.refreshed_at  # Do not extend freshness.
        return True

    def discover_files(self, *, ast_cache: dict | None = None) -> list[FileInfo]:
        """Discover all relevant files in the repository.

        Two-pass approach: collect all files (with safety ceiling), then
        score importance and truncate to a dynamic cap. This ensures
        important files deep in the alphabet aren't excluded by
        filesystem traversal order.

        Returns:
            List of FileInfo objects for discovered files.
        """
        root = Path(self.root_dir)
        resolved_root = root.resolve()
        from attocode_intel._internal.integrations.context.discovery_snapshot import (
            MAX_GUARDS,
            DiscoverySnapshot,
            path_signature,
        )
        from attocode_intel._internal.integrations.utilities.ignore import IgnoreManager

        self._discovery_snapshot = None
        guards = {}
        snapshot_safe = True
        def guard(path, *, missing_ok=False):
            nonlocal snapshot_safe
            if not snapshot_safe:
                return
            if len(guards) >= MAX_GUARDS:
                snapshot_safe = False
                guards.clear()
                return
            try:
                signature = path_signature(str(path))
                if signature is None and not missing_ok:
                    snapshot_safe = False
                if str(path) in guards and guards[str(path)] != signature:
                    snapshot_safe = False
                guards.setdefault(str(path), signature)
            except (OSError, RuntimeError):
                snapshot_safe = False

        # Record before reading rules/content; validation catches intervening edits.
        guard(root)  # Before os.walk enumerates this directory.
        guard(root / ".gitignore", missing_ok=True)
        ignore = IgnoreManager(root, default_dirs=self.ignore_patterns)
        files: list[FileInfo] = []
        _SAFETY_CEILING = 50_000  # noqa: N806  # OOM guard for massive repos
        self._ignored_checkout_dirs = []
        self._ignored_checkout_dirs_capped = False

        for dirpath, dirnames, filenames in os.walk(root):
            self._check_cancelled()
            guard(dirpath)
            # Filter ignored directories (in-place to prevent os.walk descent)
            kept_dirs = []
            for directory in dirnames:
                if directory.startswith("."):
                    continue
                path = Path(dirpath) / directory
                rel_path = path.relative_to(root).as_posix()
                if ignore.is_ignored(rel_path + "/"):
                    if not path.is_symlink():
                        if len(self._ignored_checkout_dirs) < 32:
                            self._ignored_checkout_dirs.append(rel_path)
                        else:
                            self._ignored_checkout_dirs_capped = True
                else:
                    guard(path)  # Before os.walk descends/enumerates.
                    kept_dirs.append(directory)
            # Sorted names: the file system order differs between macOS and Linux, and files of
            # equal importance keep the walk order through the sort and the cap below.
            dirnames[:] = sorted(kept_dirs)

            for filename in sorted(filenames):
                self._check_cancelled()
                if filename.startswith("."):
                    continue
                if filename in SKIP_FILENAMES:
                    continue
                ext = Path(filename).suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue

                full_path = os.path.join(dirpath, filename)
                guard(full_path)
                # os.walk does not descend through directory links, but file
                # links still appear in filenames. Do not read outside source.
                if os.path.islink(full_path):
                    try:
                        target = Path(full_path).resolve(strict=True)
                        if not target.is_relative_to(resolved_root):
                            continue
                    except (OSError, RuntimeError):
                        continue
                try:
                    rel_path = os.path.relpath(full_path, root)
                except ValueError:
                    continue
                if ignore.is_ignored(rel_path):
                    continue

                lang = EXTENSION_LANGUAGES.get(ext, "")

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0

                # Skip very large files
                if size > 1_000_000:  # 1MB
                    continue

                is_test = any(p in rel_path.lower() for p in TEST_PATTERNS)
                is_config = any(p in rel_path.lower() for p in CONFIG_PATTERNS)

                # Estimate line count (only for source files with a recognized lang)
                line_count = 0
                if lang and size < 500_000:
                    try:
                        with open(full_path, encoding="utf-8", errors="ignore") as f:
                            line_count = sum(1 for _ in f)
                    except OSError:
                        pass

                files.append(FileInfo(
                    path=full_path,
                    relative_path=rel_path,
                    size=size,
                    language=lang,
                    is_test=is_test,
                    is_config=is_config,
                    line_count=line_count,
                ))

                if len(files) >= _SAFETY_CEILING:
                    break

            if len(files) >= _SAFETY_CEILING:
                break

        # Score importance
        for f in files:
            f.importance = self._score_importance(f)

        # Build dependency graph and boost hub files using PageRank
        # Skip for large repos (>5K source files) — dep graph parsing is the
        # main bootstrap bottleneck.  Heuristic importance is good enough for
        # skeleton init; full dep graph is built during background hydration.
        source_count = sum(1 for f in files if f.language)
        if source_count < 5_000:
            self._dep_graph = build_dependency_graph(files, self.root_dir, ast_cache=ast_cache,
                                                     check_cancelled=self._check_cancelled)
            pr_scores = self._dep_graph.pagerank()
            for f in files:
                pr = pr_scores.get(f.relative_path, 0.0)
                # Normalize PageRank to 0.0-0.3 boost range
                hub_boost = pr * 0.3
                if hub_boost > 0.01:
                    f.importance = min(1.0, f.importance + hub_boost)
        else:
            self._dep_graph = DependencyGraph()  # empty placeholder

        # Sort by importance (highest first)
        files.sort(key=lambda f: f.importance, reverse=True)

        # Truncate to dynamic cap AFTER scoring (smart truncation)
        cap = _compute_dynamic_cap(files, self.max_files)
        self.discovered_file_count = len(files)
        self.discovery_truncated = len(files) > cap
        if len(files) > cap:
            files = files[:cap]

        self._files = files
        self.refresh_excluded_checkout_roots()
        self._last_refresh_time = time.monotonic()
        if snapshot_safe and not self.discovery_truncated and self.discovered_file_count < _SAFETY_CEILING:
            self._discovery_snapshot = DiscoverySnapshot(
                os.path.abspath(self.root_dir), frozenset(self.ignore_patterns),
                self._last_refresh_time,
                tuple((f.path, f.relative_path, f.size, f.language, f.importance,
                       f.is_test, f.is_config, f.line_count) for f in files),
                tuple(guards.items()),
            )
        return files

    @property
    def dependency_graph(self) -> DependencyGraph | None:
        """Get the dependency graph (available after discover_files)."""
        return self._dep_graph

    def get_repo_map(
        self,
        *,
        include_symbols: bool = False,
        max_tokens: int | None = None,
    ) -> RepoMap:
        """Generate a repository map.

        Args:
            include_symbols: If True, annotate files with top-level symbols.
            max_tokens: When set, produce a token-budgeted tree using
                importance tiers.  Files are partitioned into:
                - **Tier 1** (importance >= 0.7): shown WITH symbols (up to 5)
                - **Tier 2** (importance >= 0.4): shown WITHOUT symbols
                - **Tier 3** (below 0.4): collapsed as ``... +N files`` per dir
                When ``None`` (default), the full unbounded tree is returned
                (backward-compatible).

        Returns:
            RepoMap with tree view and file information.
        """
        if self._repo_map is not None and not include_symbols and max_tokens is None:
            return self._repo_map

        if not self._files:
            self.discover_files()

        # Collect symbols per file if requested
        file_symbols: dict[str, list[str]] = {}
        if include_symbols:
            file_symbols = self._collect_symbols()

        # Build tree — budgeted or full
        if max_tokens is not None:
            tree, included_symbols = self._build_budgeted_tree(
                max_tokens, file_symbols,
            )
            # Narrow symbols dict to only included files
            file_symbols = included_symbols
        else:
            tree = self._build_tree(file_symbols=file_symbols)

        # Compute language stats
        languages: dict[str, int] = {}
        total_lines = 0
        for f in self._files:
            if f.language:
                languages[f.language] = languages.get(f.language, 0) + 1
            total_lines += f.line_count

        repo_map = RepoMap(
            tree=tree,
            files=self._files,
            total_files=len(self._files),
            total_lines=total_lines,
            languages=languages,
            symbols=file_symbols,
        )

        if not include_symbols and max_tokens is None:
            self._repo_map = repo_map

        return repo_map

    def get_preseed_map(self, max_tokens: int = 6000) -> RepoMap:
        """Convenience wrapper for preseed injection.

        Returns a token-budgeted repo map suitable for injecting into
        the initial system context without blowing up the context window.

        Args:
            max_tokens: Token budget for the tree + symbols output.
        """
        return self.get_repo_map(include_symbols=True, max_tokens=max_tokens)

    def _collect_symbols(self) -> dict[str, list[str]]:
        """Collect top-level symbols for all parseable files.

        Prefers the ASTService cache (if available and initialized)
        over re-parsing each file.
        """
        file_symbols: dict[str, list[str]] = {}

        # Try ASTService cache first
        ast_cache: dict[str, Any] | None = None
        try:
            from attocode_intel._internal.integrations.context.ast_service import ASTService
            svc = ASTService.get_instance(self.root_dir)
            if svc.initialized:
                ast_cache = svc._ast_cache
        except Exception:
            pass

        from attocode_intel._internal.integrations.context.codebase_ast import (
            parse_file as _parse_file,
        )

        _SYMBOL_LANGS = {"python", "javascript", "typescript", "rust", "go", "java", "ruby", "c", "cpp"}  # noqa: N806
        for f in self._files:
            if f.language not in _SYMBOL_LANGS:
                continue
            try:
                # Use cached AST when available
                if ast_cache and f.relative_path in ast_cache:
                    ast = ast_cache[f.relative_path]
                else:
                    ast = _parse_file(f.path)
                syms = ast.get_symbols()
                if syms:
                    file_symbols[f.relative_path] = syms[:15]  # Cap at 15 symbols
            except Exception:
                pass
        return file_symbols

    def get_tree_view(self, max_depth: int = 3) -> str:
        """Get a lightweight tree view of the repository.

        Args:
            max_depth: Maximum directory depth to show.

        Returns:
            Text tree view string.
        """
        return self._build_tree(max_depth=max_depth)

    def select_context(
        self,
        query: str = "",
        strategy: str = "importance",
        max_files: int = 20,
    ) -> list[FileInfo]:
        """Select the most relevant files for context.

        Args:
            query: Optional query to influence selection.
            strategy: Selection strategy ('importance', 'relevance', 'breadth').
            max_files: Maximum files to include.

        Returns:
            Selected files.
        """
        self._ensure_fresh()

        if strategy == "relevance" and query:
            return self._select_by_relevance(query, max_files)
        elif strategy == "breadth":
            return self._select_by_breadth(max_files)
        else:
            # Default: importance-based
            return self._files[:max_files]

    def format_context(
        self,
        files: list[FileInfo] | None = None,
        include_content: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Format selected files as context for LLM prompt.

        Args:
            files: Files to include (defaults to top by importance).
            include_content: Whether to include file contents.
            max_tokens: Token budget for context.

        Returns:
            Formatted context string.
        """
        if files is None:
            files = self.select_context(max_files=15)

        max_tok = max_tokens or self.max_context_tokens
        from attocode_intel._internal.integrations.utilities.token_estimate import estimate_tokens

        parts = ["## Repository Context\n"]
        parts.append(f"Files: {len(self._files)} | ")
        parts.append(f"Languages: {', '.join(sorted(self.get_repo_map().languages.keys()))}\n")
        parts.append("\n### Key Files\n")

        token_count = estimate_tokens("\n".join(parts))

        for f in files:
            entry = f"- `{f.relative_path}` ({f.line_count}L, {f.language})"
            entry_tokens = estimate_tokens(entry)

            if include_content and f.size < 50_000:
                try:
                    content = Path(f.path).read_text(encoding="utf-8", errors="ignore")
                    content_entry = f"\n```{f.language}\n# {f.relative_path}\n{content}\n```\n"
                    content_tokens = estimate_tokens(content_entry)
                    if token_count + content_tokens <= max_tok:
                        entry = entry + content_entry
                        entry_tokens += content_tokens
                except OSError:
                    pass

            if token_count + entry_tokens > max_tok:
                break

            parts.append(entry)
            token_count += entry_tokens

        return "\n".join(parts)

    # --- Post-compaction file restoration ---

    def get_top_files_by_importance(
        self,
        *,
        max_files: int = 5,
        max_tokens: int = 50_000,
        exclude_patterns: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return top-N files by importance score that fit within token budget.

        Uses existing PageRank-boosted importance scores to identify the most
        important files in the current project context. Used by post-compaction
        restoration to re-inject critical context.

        Files are drawn from the discovered file list (``self._files``), which
        is sorted by importance descending after ``discover_files()`` applies
        heuristic scoring plus PageRank hub boosts.

        Args:
            max_files: Maximum number of files to return.
            max_tokens: Maximum total estimated tokens across all returned files.
            exclude_patterns: Glob patterns to exclude (e.g.,
                ``["*.test.*", "node_modules/*"]``).

        Returns:
            List of ``(relative_path, importance_score)`` tuples, sorted by
            score descending.
        """
        self._ensure_fresh()

        if not self._files:
            return []

        # Apply exclusion patterns
        candidates = self._files
        if exclude_patterns:
            import fnmatch

            def _excluded(rel_path: str) -> bool:
                return any(
                    fnmatch.fnmatch(rel_path, pat) for pat in exclude_patterns  # type: ignore[arg-type]
                )

            candidates = [f for f in candidates if not _excluded(f.relative_path)]

        # Select files within token budget
        # Files are already sorted by importance (descending) from discover_files()
        result: list[tuple[str, float]] = []
        remaining_tokens = max_tokens

        for file_info in candidates:
            if len(result) >= max_files:
                break

            # Estimate tokens from file size (size in bytes / CHARS_PER_TOKEN)
            est_tokens = max(1, int(file_info.size / CHARS_PER_TOKEN))

            if est_tokens > remaining_tokens:
                continue  # Skip files that don't fit, try smaller ones

            result.append((file_info.relative_path, file_info.importance))
            remaining_tokens -= est_tokens

        return result

    # --- Recursive context retrieval ---

    def get_recursive_context(
        self,
        seed_files: list[str],
        token_budget: int = 20_000,
        max_depth: int = 3,
        max_files: int = 15,
    ) -> str:
        """Gather context by recursively following imports from seed files.

        Uses the RecursiveContextRetriever to mechanically follow Python/JS
        imports starting from seed files, gathering content up to a depth
        and token budget. Zero LLM cost.

        Args:
            seed_files: Files to start traversal from.
            token_budget: Maximum tokens to gather.
            max_depth: Maximum import-following depth.
            max_files: Maximum files to visit.

        Returns:
            Combined content from all gathered files.
        """
        from attocode_intel._internal.tricks.recursive_context import RecursiveContextRetriever

        class _FileProvider:
            def __init__(self, root: str) -> None:
                self._root = os.path.realpath(root)

            def get_content(self, path: str) -> str | None:
                candidate = os.path.normpath(os.path.join(self._root, path))
                if not candidate.startswith(self._root):
                    return None  # Path traversal rejected
                try:
                    with open(candidate, encoding="utf-8", errors="replace") as f:
                        return f.read()
                except (OSError, UnicodeDecodeError):
                    return None

        retriever = RecursiveContextRetriever(
            _FileProvider(self.root_dir),
            max_depth=max_depth,
            token_budget=token_budget,
            max_files=max_files,
        )
        result = retriever.retrieve(seed_files)
        return result.content

    # --- Incremental update API ---

    def mark_file_dirty(self, file_path: str) -> None:
        """Mark a file as needing re-analysis after edit.

        Args:
            file_path: Absolute or relative path of the edited file.
        """
        self._discovery_snapshot = None
        # Normalize to relative path
        try:
            rel = os.path.relpath(file_path, self.root_dir) if os.path.isabs(file_path) else os.path.normpath(file_path)
        except ValueError:
            rel = file_path
        self._dirty_files.add(rel)

    def invalidate_file(self, file_path: str) -> None:
        """Remove cached AST and analysis for a specific file.

        Args:
            file_path: Path of the file to invalidate.
        """
        try:
            rel = os.path.relpath(file_path, self.root_dir) if os.path.isabs(file_path) else os.path.normpath(file_path)
        except ValueError:
            rel = file_path
        self._ast_cache.pop(rel, None)
        self._ast_cache.pop(file_path, None)
        # Also invalidate repo map cache since it may reference stale symbols
        self._repo_map = None

    def update_dirty_files(self) -> list[Any]:
        """Re-parse only dirty files and update the dependency graph incrementally.

        Returns:
            List of FileChangeResult objects describing what changed.
        """
        if not self._dirty_files:
            return []

        from attocode_intel._internal.integrations.context.codebase_ast import (
            DependencyChanges,
            FileChangeResult,
            SymbolChange,
            diff_file_ast,
            diff_imports,
            parse_file,
        )

        results: list[Any] = []
        file_index = _build_file_index(self._files, self.root_dir)

        for rel_path in list(self._dirty_files):
            # Find absolute path
            abs_path = os.path.join(self.root_dir, rel_path)

            # Handle deleted files
            if not Path(abs_path).exists():
                old_ast = self._ast_cache.pop(rel_path, None)
                # Emit removal changes for all symbols in old AST
                if old_ast is not None:
                    for func in old_ast.functions:
                        results.append(FileChangeResult(
                            file_path=rel_path,
                            symbol_changes=[SymbolChange(
                                kind="removed", symbol_name=func.name,
                                symbol_kind="function", file_path=rel_path,
                                previous=func,
                            )],
                            dependency_changes=DependencyChanges(),
                            was_incremental=True,
                        ))
                    for cls in old_ast.classes:
                        results.append(FileChangeResult(
                            file_path=rel_path,
                            symbol_changes=[SymbolChange(
                                kind="removed", symbol_name=cls.name,
                                symbol_kind="class", file_path=rel_path,
                                previous=cls,
                            )],
                            dependency_changes=DependencyChanges(),
                            was_incremental=True,
                        ))
                # Remove dependency edges
                if self._dep_graph is not None:
                    old_imports = self._dep_graph.forward.pop(rel_path, set())
                    for target in old_imports:
                        rev = self._dep_graph.reverse.get(target)
                        if rev:
                            rev.discard(rel_path)
                            if not rev:
                                del self._dep_graph.reverse[target]
                    # Also remove as a reverse dep target
                    importers = self._dep_graph.reverse.pop(rel_path, set())
                    for importer in importers:
                        self._dep_graph.forward.get(importer, set()).discard(rel_path)
                    self._dep_graph.unresolved.pop(rel_path, None)
                self._file_mtimes.pop(rel_path, None)
                continue

            # Get old AST from cache
            old_ast = self._ast_cache.get(rel_path)

            # Parse new content
            try:
                new_ast = parse_file(abs_path)
            except Exception:
                continue

            # Compute diffs
            if old_ast is not None:
                symbol_changes = diff_file_ast(old_ast, new_ast)
                dep_changes = diff_imports(old_ast, new_ast)
            else:
                symbol_changes = []
                dep_changes = DependencyChanges()

            # Update AST cache
            self._ast_cache[rel_path] = new_ast

            # Update dependency graph incrementally
            if self._dep_graph is not None and dep_changes:
                # Remove old edges for this file
                old_imports = self._dep_graph.forward.pop(rel_path, set())
                for target in old_imports:
                    rev = self._dep_graph.reverse.get(target)
                    if rev:
                        rev.discard(rel_path)
                        if not rev:
                            del self._dep_graph.reverse[target]

                # Add new edges
                self._dep_graph.unresolved.pop(rel_path, None)
                for imp in new_ast.imports:
                    targets = resolve_import_targets(new_ast.language, imp.module, rel_path, file_index, include_system=imp.include_system)
                    for target in targets:
                        if target != rel_path:
                            self._dep_graph.add_edge(rel_path, target)
                    if not targets:
                        self._dep_graph.unresolved.setdefault(rel_path, []).append(imp.module)

            # Update file mtime
            try:
                self._file_mtimes[rel_path] = os.path.getmtime(abs_path)
            except OSError:
                pass

            results.append(FileChangeResult(
                file_path=rel_path,
                symbol_changes=symbol_changes,
                dependency_changes=dep_changes,
                was_incremental=True,
            ))

        # Invalidate repo map (symbols may have changed)
        self._repo_map = None
        self._dirty_files.clear()

        return results

    def _score_importance(self, file: FileInfo) -> float:
        """Score file importance (0.0 - 1.0).

        Heuristic scoring based on:
        - Entry points (main, cli) score highest
        - Config files score high
        - Source files score by size (moderate = best)
        - Test files score lower
        """
        score = 0.5  # Base

        name = Path(file.relative_path).name.lower()
        _rel = file.relative_path.lower()

        # Entry points
        if name in ("main.py", "main.ts", "app.py", "app.ts", "cli.py", "cli.ts"):
            score += 0.3
        elif name in ("__init__.py", "index.ts", "index.js"):
            score += 0.1

        # Config files
        if file.is_config:
            score += 0.2
        if name in ("pyproject.toml", "package.json", "cargo.toml"):
            score += 0.15

        # Source vs test
        if file.is_test:
            score -= 0.2

        # Moderate-size files are often more important
        if 50 < file.line_count < 500:
            score += 0.1
        elif file.line_count > 1000:
            score += 0.05
        elif file.line_count < 10:
            score -= 0.1

        # Depth penalty (deeply nested = less important)
        depth = file.relative_path.count(os.sep)
        score -= depth * 0.03

        # README and docs
        if name in ("readme.md", "readme.rst", "readme.txt"):
            score += 0.25

        return max(0.0, min(1.0, score))

    def _select_by_relevance(self, query: str, max_files: int) -> list[FileInfo]:
        """Select files by relevance to a query (keyword + symbol matching)."""
        query_lower = query.lower()
        keywords = query_lower.split()

        # Try to get symbol names from AST service for content matching
        symbol_names: dict[str, list[str]] = {}
        try:
            from attocode_intel._internal.integrations.context.ast_service import ASTService
            svc = ASTService.get_instance(self._root_dir)
            if svc.initialized:
                for f in self._files:
                    syms = svc.get_symbol_names(f.relative_path)
                    if syms:
                        symbol_names[f.relative_path] = [s.lower() for s in syms]
        except Exception:
            pass

        _CONFIG_NAMES = frozenset({  # noqa: N806
            "pyproject.toml", "package.json", "tsconfig.json", "setup.cfg",
            "setup.py", "readme.md", "changelog.md",
        })

        scored: list[tuple[float, FileInfo]] = []
        for f in self._files:
            rel_lower = f.relative_path.lower()
            basename_lower = os.path.basename(rel_lower)

            # Path keyword matching
            path_score = sum(1 for kw in keywords if kw in rel_lower)

            # Symbol name matching (content-aware)
            sym_score = 0
            file_syms = symbol_names.get(f.relative_path, [])
            for kw in keywords:
                for sym in file_syms:
                    if kw in sym:
                        sym_score += 1
                        break

            # Config file penalty
            config_penalty = 1.0
            if basename_lower in _CONFIG_NAMES or f.is_config:
                config_penalty = 0.3

            # Compute final score: reduced importance weight, boosted content match
            base = f.importance * 0.3  # Reduced from 1.0
            match_bonus = path_score * 0.3 + sym_score * 0.5
            score = (base + match_bonus) * config_penalty

            scored.append((score, f))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:max_files]]

    def _select_by_breadth(self, max_files: int) -> list[FileInfo]:
        """Select files for broad coverage across directories."""
        seen_dirs: set[str] = set()
        selected: list[FileInfo] = []

        for f in self._files:
            parent = str(Path(f.relative_path).parent)
            if parent not in seen_dirs or len(selected) < max_files // 2:
                selected.append(f)
                seen_dirs.add(parent)
            if len(selected) >= max_files:
                break

        return selected

    # ------ Budgeted tree helpers ------

    def _build_budgeted_tree(
        self,
        max_tokens: int,
        file_symbols: dict[str, list[str]],
    ) -> tuple[str, dict[str, list[str]]]:
        """Build a token-budgeted tree using importance tiers.

        Files are partitioned into three tiers based on importance:
        - **Tier 1** (>= 0.7): appear in tree WITH up to 5 symbols each
        - **Tier 2** (>= 0.4): appear in tree WITHOUT symbols
        - **Tier 3** (< 0.4): collapsed as ``... +N files`` per directory

        The builder tracks estimated token count and stops adding entries
        once *max_tokens* is reached.

        Returns:
            ``(tree_text, included_symbols)`` — the rendered tree string
            and the symbols dict narrowed to only Tier 1 files.
        """
        from attocode_intel._internal.integrations.utilities.token_estimate import estimate_tokens

        tier1: list[FileInfo] = []
        tier2: list[FileInfo] = []
        tier3: list[FileInfo] = []

        for f in self._files:
            if f.importance >= 0.7:
                tier1.append(f)
            elif f.importance >= 0.4:
                tier2.append(f)
            else:
                tier3.append(f)

        # Build included set (Tier 1 + Tier 2 files shown individually)
        included_set = {f.relative_path for f in tier1} | {f.relative_path for f in tier2}

        # Narrow symbols to Tier 1 only, capped at 5 per file
        included_symbols: dict[str, list[str]] = {}
        for f in tier1:
            syms = file_symbols.get(f.relative_path, [])
            if syms:
                included_symbols[f.relative_path] = syms[:10]

        # Count omitted files per directory for collapse annotations
        omitted_per_dir = self._count_omitted_per_dir(
            [f.relative_path for f in self._files], included_set,
        )

        # Build tree dict from included files
        root = Path(self.root_dir)
        tree_dict: dict[str, Any] = {}
        leaf_rel_paths: dict[str, str] = {}
        max_depth = 6

        for f in tier1 + tier2:
            parts = Path(f.relative_path).parts
            if len(parts) > max_depth + 1:
                parts = parts[:max_depth] + ("...",)
            current = tree_dict
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = None
            leaf_rel_paths[parts[-1]] = f.relative_path

        # Inject collapse markers (``... +N files``) into directory nodes
        for dir_path, count in sorted(omitted_per_dir.items()):
            parts = Path(dir_path).parts if dir_path != "." else ()
            current = tree_dict
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
                if current is None:
                    break
            if isinstance(current, dict):
                current[f"... +{count} files"] = None

        lines = [str(root.name) + "/"]
        self._format_tree_dict(
            tree_dict, lines, prefix="",
            file_symbols=included_symbols, leaf_rel_paths=leaf_rel_paths,
        )

        tree_text = "\n".join(lines)

        # Truncate to budget if still over
        tokens = estimate_tokens(tree_text)
        if tokens > max_tokens:
            # Progressively trim lines from the end (least important)
            while lines and estimate_tokens("\n".join(lines)) > max_tokens:
                lines.pop()
            if lines:
                lines.append(f"... (truncated, {len(self._files)} total files)")
            tree_text = "\n".join(lines)

        return tree_text, included_symbols

    @staticmethod
    def _count_omitted_per_dir(
        all_paths: list[str],
        included_set: set[str],
    ) -> dict[str, int]:
        """Count how many files per directory were omitted (Tier 3).

        Returns:
            ``{dir_relative_path: count}`` for directories with omitted files.
        """
        counts: dict[str, int] = {}
        for path in all_paths:
            if path not in included_set:
                parent = str(Path(path).parent)
                counts[parent] = counts.get(parent, 0) + 1
        return counts

    def _build_tree(
        self,
        max_depth: int = 4,
        file_symbols: dict[str, list[str]] | None = None,
    ) -> str:
        """Build a text tree view of the repository.

        Args:
            max_depth: Maximum directory nesting to display.
            file_symbols: Optional map of relative_path -> symbol names to show.
        """
        if not self._files:
            return "(no files discovered)"

        root = Path(self.root_dir)
        tree_dict: dict[str, Any] = {}
        # Track relative path per leaf for symbol lookup
        leaf_rel_paths: dict[str, str] = {}

        for f in self._files:
            parts = Path(f.relative_path).parts
            if len(parts) > max_depth + 1:
                parts = parts[:max_depth] + ("...",)

            current = tree_dict
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = None  # Leaf file
            leaf_rel_paths[parts[-1]] = f.relative_path

        lines = [str(root.name) + "/"]
        self._format_tree_dict(tree_dict, lines, prefix="", file_symbols=file_symbols, leaf_rel_paths=leaf_rel_paths)
        return "\n".join(lines)

    def _format_tree_dict(
        self,
        d: dict[str, Any],
        lines: list[str],
        prefix: str,
        file_symbols: dict[str, list[str]] | None = None,
        leaf_rel_paths: dict[str, str] | None = None,
    ) -> None:
        """Recursively format tree dict into lines."""
        items = sorted(d.items(), key=lambda x: (x[1] is not None, x[0]))
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if subtree is not None else ""

            # Annotate leaf files with symbols
            sym_annotation = ""
            if file_symbols and subtree is None and leaf_rel_paths:
                rel_path = leaf_rel_paths.get(name, "")
                syms = file_symbols.get(rel_path, [])
                if syms:
                    sym_annotation = "  [" + ", ".join(syms) + "]"

            lines.append(f"{prefix}{connector}{name}{suffix}{sym_annotation}")

            if subtree is not None:
                next_prefix = prefix + ("    " if is_last else "│   ")
                self._format_tree_dict(subtree, lines, next_prefix, file_symbols, leaf_rel_paths)
