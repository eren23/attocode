"""Tests for ignore manager."""

from __future__ import annotations

from attocode.integrations.utilities.ignore import IgnoreManager


class TestIgnoreManager:
    def test_builtin_ignores(self) -> None:
        im = IgnoreManager("/nonexistent")
        assert im.is_ignored(".git/HEAD")
        assert im.is_ignored("node_modules/package.json")
        assert im.is_ignored("__pycache__/mod.pyc")
        assert im.is_ignored(".venv/bin/python")

    def test_normal_files_not_ignored(self) -> None:
        im = IgnoreManager("/nonexistent")
        assert not im.is_ignored("src/main.py")
        assert not im.is_ignored("README.md")

    def test_filter_paths(self) -> None:
        im = IgnoreManager("/nonexistent")
        paths = ["src/main.py", "node_modules/foo.js", "README.md", ".git/config"]
        filtered = im.filter_paths(paths)
        assert "src/main.py" in filtered
        assert "README.md" in filtered
        assert "node_modules/foo.js" not in filtered

    def test_gitignore_loading(self, tmp_path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\nbuild/\n")
        im = IgnoreManager(tmp_path)
        assert im.is_ignored("debug.log")
        assert im.is_ignored("build/output.js")
        assert not im.is_ignored("src/main.py")

    def test_gitignore_comments(self, tmp_path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# comment\n*.tmp\n")
        im = IgnoreManager(tmp_path)
        assert im.is_ignored("file.tmp")
        # Comment lines should not be treated as patterns
        assert not im.is_ignored("# comment")

    def test_reload(self, tmp_path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n")
        im = IgnoreManager(tmp_path)
        assert im.is_ignored("test.log")

        gitignore.write_text("*.tmp\n")
        im.reload()
        assert im.is_ignored("test.tmp")
