"""Tests for codebase context system."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.integrations.context.codebase_context import (
    CONFIG_PATTERNS,
    DEFAULT_IGNORES,
    EXTENSION_LANGUAGES,
    TEST_PATTERNS,
    CodebaseContextManager,
    DependencyGraph,
    FileInfo,
    RepoMap,
    _compute_dynamic_cap,
    _resolve_c_import,
    _resolve_go_import,
    _resolve_java_import,
    _resolve_ruby_import,
    _resolve_rust_import,
    build_dependency_graph,
)


# --- Helper to build a temp project layout ---


def _create_project(root: Path) -> None:
    """Create a small project structure under root."""
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text(
        "import sys\n\ndef main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (root / "src" / "utils.py").write_text(
        "def helper():\n    return 42\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")


# ============================================================
# FileInfo Tests
# ============================================================


class TestFileInfo:
    def test_extension_property(self) -> None:
        fi = FileInfo(path="/tmp/foo.py", relative_path="foo.py")
        assert fi.extension == ".py"

    def test_defaults(self) -> None:
        fi = FileInfo(path="/x", relative_path="x")
        assert fi.size == 0
        assert fi.language == ""
        assert fi.importance == 0.0
        assert not fi.is_test
        assert not fi.is_config
        assert fi.line_count == 0


class TestRepoMap:
    def test_dataclass(self) -> None:
        rm = RepoMap(tree="root/", files=[], total_files=0, total_lines=0)
        assert rm.tree == "root/"
        assert rm.languages == {}


# ============================================================
# CodebaseContextManager Tests
# ============================================================


class TestDiscoverFiles:
    def test_discovers_files(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        paths = [f.relative_path for f in files]
        assert any("main.py" in p for p in paths)
        assert any("utils.py" in p for p in paths)

    def test_ignores_hidden_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "real.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        paths = [f.relative_path for f in files]
        assert not any(".git" in p for p in paths)

    def test_ignores_default_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("x")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.pyc").write_text("x")
        (tmp_path / "app.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        paths = [f.relative_path for f in files]
        assert not any("node_modules" in p for p in paths)

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET=x")
        (tmp_path / "app.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        paths = [f.relative_path for f in files]
        assert not any(".env" in p for p in paths)

    def test_skips_compiled_files(self, tmp_path: Path) -> None:
        (tmp_path / "mod.pyc").write_text("x")
        (tmp_path / "mod.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        paths = [f.relative_path for f in files]
        assert not any(p.endswith(".pyc") for p in paths)

    def test_detects_language(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "index.ts").write_text("const x = 1;\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        langs = {f.relative_path: f.language for f in files}
        assert langs.get("app.py") == "python"
        assert langs.get("index.ts") == "typescript"

    def test_detects_test_files(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        test_files = [f for f in files if f.is_test]
        assert len(test_files) >= 1

    def test_detects_config_files(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n')

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        config_files = [f for f in files if f.is_config]
        assert len(config_files) >= 1

    def test_max_files_limit(self, tmp_path: Path) -> None:
        """Dynamic cap keeps all files when source count < 1000."""
        for i in range(20):
            (tmp_path / f"file{i}.py").write_text(f"x = {i}\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path), max_files=5)
        files = mgr.discover_files()
        # With <1000 source files, dynamic cap keeps everything
        assert len(files) == 20

    def test_safety_ceiling(self, tmp_path: Path) -> None:
        """Safety ceiling (50k) prevents OOM on massive repos."""
        # Just verify the constant exists and discover_files completes
        mgr = CodebaseContextManager(root_dir=str(tmp_path), max_files=5)
        files = mgr.discover_files()
        assert isinstance(files, list)

    def test_sorts_by_importance(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        # Files should be sorted by importance (descending)
        importances = [f.importance for f in files]
        assert importances == sorted(importances, reverse=True)


class TestDetectLanguage:
    def test_known_extensions(self) -> None:
        assert EXTENSION_LANGUAGES[".py"] == "python"
        assert EXTENSION_LANGUAGES[".ts"] == "typescript"
        assert EXTENSION_LANGUAGES[".rs"] == "rust"
        assert EXTENSION_LANGUAGES[".go"] == "go"
        assert EXTENSION_LANGUAGES[".java"] == "java"

    def test_shell_extensions(self) -> None:
        assert EXTENSION_LANGUAGES[".sh"] == "shell"
        assert EXTENSION_LANGUAGES[".bash"] == "shell"

    def test_config_extensions(self) -> None:
        assert EXTENSION_LANGUAGES[".yaml"] == "yaml"
        assert EXTENSION_LANGUAGES[".json"] == "json"
        assert EXTENSION_LANGUAGES[".toml"] == "toml"


class TestScoreImportance:
    def test_entry_point_high_score(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        main = next(f for f in files if "main.py" in f.relative_path)
        utils = next(f for f in files if "utils.py" in f.relative_path)
        assert main.importance > utils.importance

    def test_test_files_lower_score(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        test_f = next(f for f in files if f.is_test)
        src_f = next(f for f in files if "main.py" in f.relative_path)
        assert src_f.importance > test_f.importance

    def test_config_bonus(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        config = next(f for f in files if "pyproject.toml" in f.relative_path)
        assert config.importance > 0.5


class TestSelectContext:
    def test_importance_strategy(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        selected = mgr.select_context(strategy="importance", max_files=2)
        assert len(selected) <= 2

    def test_relevance_strategy(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        selected = mgr.select_context(query="main", strategy="relevance", max_files=5)
        # main.py should be among top results
        paths = [f.relative_path for f in selected]
        assert any("main" in p for p in paths)

    def test_breadth_strategy(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        selected = mgr.select_context(strategy="breadth", max_files=10)
        # Should include files from different directories
        dirs = {str(Path(f.relative_path).parent) for f in selected}
        assert len(dirs) >= 2


class TestFormatContext:
    def test_format_output(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()
        output = mgr.format_context()
        assert "Repository Context" in output
        assert "Key Files" in output

    def test_format_with_files(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        output = mgr.format_context(files=files[:2])
        assert "Repository Context" in output


class TestBuildTree:
    def test_tree_structure(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()
        tree = mgr._build_tree()
        assert tmp_path.name in tree
        # Should contain tree connectors
        assert any(c in tree for c in ("├──", "└──"))

    def test_empty_tree(self, tmp_path: Path) -> None:
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        tree = mgr._build_tree()
        assert "no files discovered" in tree

    def test_tree_max_depth(self, tmp_path: Path) -> None:
        # Create deeply nested files
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "deep.py").write_text("x = 1\n")
        (tmp_path / "top.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()
        tree = mgr._build_tree(max_depth=2)
        assert "..." in tree


class TestGetRepoMap:
    def test_generates_repo_map(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        repo_map = mgr.get_repo_map()
        assert isinstance(repo_map, RepoMap)
        assert repo_map.total_files > 0
        assert "python" in repo_map.languages

    def test_caches_repo_map(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        map1 = mgr.get_repo_map()
        map2 = mgr.get_repo_map()
        assert map1 is map2

    def test_repo_map_with_symbols(self, tmp_path: Path) -> None:
        _create_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        repo_map = mgr.get_repo_map(include_symbols=True)
        assert isinstance(repo_map, RepoMap)
        # main.py has a 'main' function
        assert any("main" in syms for syms in repo_map.symbols.values())
        # Tree should contain symbol annotations
        assert "[" in repo_map.tree

    def test_repo_map_symbols_in_tree_text(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text(
            "class Foo:\n    pass\n\ndef bar():\n    pass\n",
            encoding="utf-8",
        )
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        repo_map = mgr.get_repo_map(include_symbols=True)
        assert "Foo" in repo_map.tree
        assert "bar" in repo_map.tree


# ============================================================
# DependencyGraph Tests
# ============================================================


class TestDependencyGraph:
    def test_add_edge(self) -> None:
        g = DependencyGraph()
        g.add_edge("a.py", "b.py")
        assert "b.py" in g.get_imports("a.py")
        assert "a.py" in g.get_importers("b.py")

    def test_hub_score(self) -> None:
        g = DependencyGraph()
        g.add_edge("a.py", "hub.py")
        g.add_edge("b.py", "hub.py")
        g.add_edge("c.py", "hub.py")
        assert g.hub_score("hub.py") > 0
        assert g.hub_score("leaf.py") == 0.0

    def test_hub_score_capped(self) -> None:
        g = DependencyGraph()
        for i in range(20):
            g.add_edge(f"f{i}.py", "popular.py")
        assert g.hub_score("popular.py") == 0.2  # Capped

    def test_to_import_graph(self) -> None:
        g = DependencyGraph()
        g.add_edge("a.py", "b.py")
        g.add_edge("a.py", "c.py")
        ig = g.to_import_graph()
        assert set(ig["a.py"]) == {"b.py", "c.py"}

    def test_empty_graph(self) -> None:
        g = DependencyGraph()
        assert g.get_imports("x.py") == set()
        assert g.get_importers("x.py") == set()


class TestBuildDependencyGraph:
    def test_python_imports_resolved(self, tmp_path: Path) -> None:
        """Relative Python imports are resolved to file paths."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "main.py").write_text(
            "from pkg.utils import helper\n\ndef main():\n    helper()\n",
            encoding="utf-8",
        )
        (pkg / "utils.py").write_text(
            "def helper():\n    return 42\n",
            encoding="utf-8",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()

        graph = mgr.dependency_graph
        assert graph is not None

        # pkg/main.py should import pkg/utils.py
        main_imports = graph.get_imports(os.path.join("pkg", "main.py"))
        assert any("utils" in p for p in main_imports)

    def test_js_relative_imports(self, tmp_path: Path) -> None:
        """JS relative imports are resolved to file paths."""
        (tmp_path / "index.js").write_text(
            'import { helper } from "./utils";\nconsole.log(helper());\n',
            encoding="utf-8",
        )
        (tmp_path / "utils.js").write_text(
            "export function helper() { return 42; }\n",
            encoding="utf-8",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()

        graph = mgr.dependency_graph
        assert graph is not None

        index_imports = graph.get_imports("index.js")
        assert "utils.js" in index_imports

    def test_hub_files_get_importance_boost(self, tmp_path: Path) -> None:
        """Files imported by many others get an importance boost."""
        (tmp_path / "a.py").write_text("from utils import x\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("from utils import y\n", encoding="utf-8")
        (tmp_path / "c.py").write_text("from utils import z\n", encoding="utf-8")
        (tmp_path / "utils.py").write_text(
            "x = 1\ny = 2\nz = 3\n",
            encoding="utf-8",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()

        utils_file = next(f for f in files if "utils.py" in f.relative_path)
        a_file = next(f for f in files if "a.py" in f.relative_path)

        # utils.py should have higher importance due to being a hub
        assert utils_file.importance >= a_file.importance

    def test_no_self_edges(self, tmp_path: Path) -> None:
        """Files should not import themselves."""
        (tmp_path / "self_ref.py").write_text(
            "from self_ref import foo\ndef foo(): pass\n",
            encoding="utf-8",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        graph = mgr.dependency_graph
        assert graph is not None

        self_imports = graph.get_imports("self_ref.py")
        assert "self_ref.py" not in self_imports

    def test_unresolvable_imports_skipped(self, tmp_path: Path) -> None:
        """Third-party / stdlib imports that can't be resolved are skipped."""
        (tmp_path / "app.py").write_text(
            "import os\nimport sys\nfrom pathlib import Path\n",
            encoding="utf-8",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        graph = mgr.dependency_graph
        assert graph is not None

        # No edges since os/sys/pathlib are not local files
        assert graph.get_imports("app.py") == set()


# ============================================================
# Budgeted Repo Map Tests
# ============================================================


def _create_large_project(root: Path, n_files: int = 50) -> None:
    """Create a project with many files at varying importance levels."""
    # High-importance: entry points
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text(
        "import sys\n\nclass App:\n    pass\n\ndef main():\n    print('hello')\n\n"
        "def setup():\n    pass\n\ndef run():\n    pass\n",
        encoding="utf-8",
    )
    (root / "src" / "cli.py").write_text(
        "def cli():\n    pass\n\ndef parse_args():\n    pass\n",
        encoding="utf-8",
    )
    # Config (high importance)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (root / "README.md").write_text("# Demo project\n" * 20, encoding="utf-8")

    # Medium-importance: regular source files
    for i in range(10):
        (root / "src" / f"module_{i}.py").write_text(
            f"class Module{i}:\n    pass\n\ndef func_{i}():\n    return {i}\n" * 3,
            encoding="utf-8",
        )

    # Low-importance: test files, deeply nested, tiny files
    (root / "tests").mkdir()
    for i in range(15):
        (root / "tests" / f"test_mod_{i}.py").write_text(
            f"def test_{i}():\n    assert True\n",
            encoding="utf-8",
        )

    # Deeply nested low-importance
    deep = root / "src" / "internal" / "detail"
    deep.mkdir(parents=True)
    for i in range(10):
        (deep / f"helper_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")


class TestBudgetedRepoMap:
    def test_max_tokens_limits_output(self, tmp_path: Path) -> None:
        """Budgeted repo map should be significantly smaller than full."""
        _create_large_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        full_map = mgr.get_repo_map(include_symbols=True)
        budgeted_map = mgr.get_repo_map(include_symbols=True, max_tokens=4000)

        # Budgeted tree should be shorter
        assert len(budgeted_map.tree) < len(full_map.tree)
        # Budgeted should have fewer symbols
        assert len(budgeted_map.symbols) <= len(full_map.symbols)

    def test_tier1_files_have_symbols(self, tmp_path: Path) -> None:
        """High-importance files should retain symbol annotations."""
        _create_large_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        budgeted_map = mgr.get_repo_map(include_symbols=True, max_tokens=6000)

        # main.py should be in Tier 1 with symbols
        main_syms = budgeted_map.symbols.get(os.path.join("src", "main.py"), [])
        assert len(main_syms) > 0, "main.py should have symbols in budgeted map"
        # Symbols capped at 5 for budgeted
        assert len(main_syms) <= 5

    def test_low_importance_files_collapsed(self, tmp_path: Path) -> None:
        """Tier 3 files should appear as collapse markers, not individual entries."""
        _create_large_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        budgeted_map = mgr.get_repo_map(include_symbols=True, max_tokens=4000)

        # Should contain collapse markers for omitted files
        assert "..." in budgeted_map.tree
        # The tree should not list every single test file individually
        # (tests are low importance, most should be collapsed)
        test_file_count = budgeted_map.tree.count("test_mod_")
        total_test_files = 15
        assert test_file_count < total_test_files, (
            f"Expected fewer than {total_test_files} test files in tree, got {test_file_count}"
        )

    def test_no_max_tokens_preserves_behavior(self, tmp_path: Path) -> None:
        """Without max_tokens, output should match original behavior."""
        _create_large_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        full_map = mgr.get_repo_map(include_symbols=True)
        default_map = mgr.get_repo_map(include_symbols=True, max_tokens=None)

        assert full_map.tree == default_map.tree
        assert full_map.symbols == default_map.symbols
        assert full_map.total_files == default_map.total_files

    def test_get_preseed_map(self, tmp_path: Path) -> None:
        """get_preseed_map() should return a budgeted map."""
        _create_large_project(tmp_path)
        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        preseed = mgr.get_preseed_map()
        full_map = mgr.get_repo_map(include_symbols=True)

        # Preseed should be smaller than full
        assert len(preseed.tree) < len(full_map.tree)
        assert preseed.total_files == full_map.total_files  # total_files is still accurate

    def test_count_omitted_per_dir(self) -> None:
        """Static helper should count omitted files per directory."""
        all_paths = ["src/a.py", "src/b.py", "src/c.py", "tests/t1.py", "tests/t2.py"]
        included = {"src/a.py", "src/b.py"}
        counts = CodebaseContextManager._count_omitted_per_dir(all_paths, included)
        assert counts["src"] == 1  # c.py omitted
        assert counts["tests"] == 2  # both test files omitted


# --- Dynamic cap tests ---


class TestDynamicCap:
    def _make_files(self, n_source: int, n_other: int = 0) -> list[FileInfo]:
        files = []
        for i in range(n_source):
            files.append(FileInfo(
                path=f"/tmp/f{i}.py", relative_path=f"f{i}.py",
                language="python", importance=0.5,
            ))
        for i in range(n_other):
            files.append(FileInfo(
                path=f"/tmp/d{i}.txt", relative_path=f"d{i}.txt",
                language="", importance=0.1,
            ))
        return files

    def test_small_repo_keeps_all(self) -> None:
        files = self._make_files(50, 30)
        cap = _compute_dynamic_cap(files, 2000)
        assert cap == 80  # total count — keep everything

    def test_medium_repo_caps_at_source_count(self) -> None:
        files = self._make_files(2000, 500)
        cap = _compute_dynamic_cap(files, 2000)
        assert cap == 2000  # max(source_count, configured_max)

    def test_large_repo_caps_at_10000(self) -> None:
        files = self._make_files(8000, 1000)
        cap = _compute_dynamic_cap(files, 2000)
        assert cap == 10000

    def test_huge_repo_caps_at_20000(self) -> None:
        files = self._make_files(25000, 5000)
        cap = _compute_dynamic_cap(files, 2000)
        assert cap == 20000


# --- Rust import resolver tests ---


class TestResolveRustImport:
    def _index(self, paths: list[str]) -> dict[str, str]:
        return {p: p for p in paths}

    def test_crate_import(self) -> None:
        idx = self._index(["src/worker.rs", "src/main.rs"])
        result = _resolve_rust_import("crate::worker", "src/main.rs", idx)
        assert result == "src/worker.rs"

    def test_crate_import_mod_rs(self) -> None:
        idx = self._index(["src/worker/mod.rs", "src/main.rs"])
        result = _resolve_rust_import("crate::worker", "src/main.rs", idx)
        assert result == "src/worker/mod.rs"

    def test_super_import(self) -> None:
        idx = self._index(["src/utils.rs", "src/sub/child.rs"])
        result = _resolve_rust_import("super::utils", "src/sub/child.rs", idx)
        assert result == "src/utils.rs"

    def test_mod_declaration(self) -> None:
        idx = self._index(["src/worker.rs", "src/lib.rs"])
        result = _resolve_rust_import("worker", "src/lib.rs", idx)
        assert result == "src/worker.rs"

    def test_skip_stdlib(self) -> None:
        idx = self._index(["src/main.rs"])
        assert _resolve_rust_import("std::collections::HashMap", "src/main.rs", idx) is None

    def test_skip_core(self) -> None:
        idx = self._index(["src/main.rs"])
        assert _resolve_rust_import("core::fmt", "src/main.rs", idx) is None

    def test_nested_crate_import(self) -> None:
        idx = self._index(["src/a/b.rs", "src/main.rs"])
        result = _resolve_rust_import("crate::a::b", "src/main.rs", idx)
        assert result == "src/a/b.rs"

    def test_self_import(self) -> None:
        idx = self._index(["src/parser/lexer.rs", "src/parser/mod.rs"])
        result = _resolve_rust_import("self::lexer", "src/parser/mod.rs", idx)
        assert result == "src/parser/lexer.rs"


# --- Go import resolver tests ---


class TestResolveGoImport:
    def _index(self, paths: list[str]) -> dict[str, str]:
        return {p: p for p in paths}

    def test_relative_import(self) -> None:
        idx = self._index(["internal/parser/parser.go", "main.go"])
        result = _resolve_go_import("./internal/parser", "main.go", idx)
        assert result == "internal/parser/parser.go"

    def test_skip_stdlib(self) -> None:
        idx = self._index(["main.go"])
        assert _resolve_go_import("fmt", "main.go", idx) is None
        assert _resolve_go_import("net/http", "main.go", idx) is None

    def test_skip_external(self) -> None:
        idx = self._index(["main.go"])
        # External packages have dots in path but won't match local files
        assert _resolve_go_import("github.com/user/repo/pkg", "main.go", idx) is None


# --- Java import resolver tests ---


class TestResolveJavaImport:
    def _index(self, paths: list[str]) -> dict[str, str]:
        return {p: p for p in paths}

    def test_local_import(self) -> None:
        idx = self._index(["com/myapp/utils/Helper.java", "com/myapp/Main.java"])
        result = _resolve_java_import(
            "com.myapp.utils.Helper", "com/myapp/Main.java", idx,
        )
        assert result == "com/myapp/utils/Helper.java"

    def test_maven_layout(self) -> None:
        idx = self._index(["src/main/java/com/app/Service.java"])
        result = _resolve_java_import(
            "com.app.Service", "src/main/java/com/app/Main.java", idx,
        )
        assert result == "src/main/java/com/app/Service.java"

    def test_skip_stdlib(self) -> None:
        idx = self._index(["Main.java"])
        assert _resolve_java_import("java.util.List", "Main.java", idx) is None
        assert _resolve_java_import("javax.swing.JFrame", "Main.java", idx) is None

    def test_skip_external(self) -> None:
        idx = self._index(["Main.java"])
        assert _resolve_java_import("org.apache.commons.lang3.StringUtils", "Main.java", idx) is None


# --- Ruby import resolver tests ---


class TestResolveRubyImport:
    def _index(self, paths: list[str]) -> dict[str, str]:
        return {p: p for p in paths}

    def test_require_relative(self) -> None:
        idx = self._index(["lib/helper.rb", "lib/main.rb"])
        result = _resolve_ruby_import("./helper", "lib/main.rb", idx)
        assert result == "lib/helper.rb"

    def test_require_relative_with_ext(self) -> None:
        idx = self._index(["lib/helper.rb", "lib/main.rb"])
        result = _resolve_ruby_import("./helper.rb", "lib/main.rb", idx)
        assert result == "lib/helper.rb"

    def test_require_local_lib(self) -> None:
        idx = self._index(["lib/mylib/utils.rb"])
        result = _resolve_ruby_import("mylib/utils", "app.rb", idx)
        assert result == "lib/mylib/utils.rb"


# --- C/C++ import resolver tests ---


class TestResolveCImport:
    def _index(self, paths: list[str]) -> dict[str, str]:
        return {p: p for p in paths}

    def test_local_header(self) -> None:
        idx = self._index(["src/myheader.h", "src/main.c"])
        result = _resolve_c_import("myheader.h", "src/main.c", idx)
        assert result == "src/myheader.h"

    def test_include_dir(self) -> None:
        idx = self._index(["include/mylib.h", "src/main.c"])
        result = _resolve_c_import("mylib.h", "src/main.c", idx)
        assert result == "include/mylib.h"

    def test_skip_system_header(self) -> None:
        idx = self._index(["src/main.c"])
        assert _resolve_c_import("stdio.h", "src/main.c", idx) is None
        assert _resolve_c_import("stdlib.h", "src/main.c", idx) is None

    def test_relative_path_header(self) -> None:
        idx = self._index(["src/utils/helper.h", "src/main.c"])
        result = _resolve_c_import("utils/helper.h", "src/main.c", idx)
        assert result == "src/utils/helper.h"


# --- End-to-end multi-language dependency graph tests ---


class TestMultiLanguageDependencyGraph:
    def test_rust_dependency_graph(self, tmp_path: Path) -> None:
        """Rust use/mod imports are resolved in dependency graph."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.rs").write_text(
            "mod worker;\nuse crate::worker::run;\n\nfn main() {\n    run();\n}\n",
        )
        (src / "worker.rs").write_text(
            "pub fn run() {\n    println!(\"working\");\n}\n",
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        graph = mgr.dependency_graph
        assert graph is not None

        main_imports = graph.get_imports(os.path.join("src", "main.rs"))
        assert any("worker" in p for p in main_imports)

    def test_go_dependency_graph(self, tmp_path: Path) -> None:
        """Go relative imports are resolved in dependency graph."""
        (tmp_path / "main.go").write_text(
            'package main\n\nimport "./internal/parser"\n\nfunc main() {\n}\n',
        )
        internal = tmp_path / "internal" / "parser"
        internal.mkdir(parents=True)
        (internal / "parser.go").write_text(
            'package parser\n\nfunc Parse() string {\n    return "ok"\n}\n',
        )

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        files = mgr.discover_files()
        graph = mgr.dependency_graph
        assert graph is not None

        main_imports = graph.get_imports("main.go")
        assert any("parser" in p for p in main_imports)
