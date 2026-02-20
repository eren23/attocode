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
    FileInfo,
    RepoMap,
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
        for i in range(20):
            (tmp_path / f"file{i}.py").write_text(f"x = {i}\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path), max_files=5)
        files = mgr.discover_files()
        assert len(files) == 5

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
