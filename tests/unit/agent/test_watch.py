"""Tests for watch mode / inline triggers."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.agent.watch import (
    FileWatcher,
    TriggerMatch,
    WatchConfig,
)


class TestFileWatcher:
    def test_scan_python_trigger(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n# AI: refactor this function\ny = 2\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 1
        assert matches[0].trigger_text == "refactor this function"
        assert matches[0].line_number == 2
        assert matches[0].comment_style == "#"

    def test_scan_js_trigger(self, tmp_path: Path) -> None:
        f = tmp_path / "code.js"
        f.write_text("const x = 1;\n// AI: add error handling here\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 1
        assert matches[0].trigger_text == "add error handling here"
        assert matches[0].comment_style == "//"

    def test_scan_no_triggers(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.py"
        f.write_text("# Normal comment\nx = 1\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 0

    def test_scan_multiple_triggers(self, tmp_path: Path) -> None:
        f = tmp_path / "multi.py"
        f.write_text(
            "# AI: fix this\n"
            "x = 1\n"
            "# AI: add tests\n"
        )
        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 2

    def test_scan_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# AI: do thing A\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("# AI: do thing B\n")

        watcher = FileWatcher(WatchConfig(extensions=[".py"]))
        matches = watcher.scan_directory(tmp_path)
        assert len(matches) == 2

    def test_scan_ignores_patterns(self, tmp_path: Path) -> None:
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "bad.py").write_text("# AI: should be ignored\n")
        (tmp_path / "good.py").write_text("# AI: should be found\n")

        watcher = FileWatcher(WatchConfig(extensions=[".py"]))
        matches = watcher.scan_directory(tmp_path)
        assert len(matches) == 1
        assert "good.py" in matches[0].file_path

    def test_remove_trigger_whole_line(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n# AI: fix this\ny = 2\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 1

        result = watcher.remove_trigger(matches[0])
        assert result is True
        content = f.read_text()
        assert "AI:" not in content
        assert "x = 1" in content
        assert "y = 2" in content

    def test_remove_trigger_inline(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1  # AI: fix this\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        result = watcher.remove_trigger(matches[0])
        assert result is True
        content = f.read_text()
        assert "x = 1" in content
        assert "AI:" not in content

    def test_mark_processed(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("# AI: do thing\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        watcher.mark_processed(matches[0])

        # Second scan should filter out processed triggers
        config = WatchConfig(watch_dirs=[str(tmp_path)], extensions=[".py"])
        watcher2 = FileWatcher(config)
        watcher2._processed_triggers = watcher._processed_triggers
        matches2 = watcher2.scan_directory(tmp_path)
        assert len(matches2) == 0

    def test_check_for_changes(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("v1")

        config = WatchConfig(watch_dirs=[str(tmp_path)], extensions=[".py"])
        watcher = FileWatcher(config)

        # First check — establishes baseline
        changed = watcher.check_for_changes()
        # All files are new so nothing "changed" (no previous mtime)
        assert isinstance(changed, list)

        # Modify file
        f.write_text("v2")
        changed = watcher.check_for_changes()
        assert len(changed) >= 1

    def test_scan_all(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# AI: task A\n")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "b.py").write_text("# AI: task B\n")

        config = WatchConfig(watch_dirs=[str(tmp_path)], extensions=[".py"])
        watcher = FileWatcher(config)
        matches = watcher.scan_all()
        assert len(matches) == 2

    def test_empty_trigger_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("# AI:\n")

        watcher = FileWatcher()
        matches = watcher.scan_file(f)
        assert len(matches) == 0

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        watcher = FileWatcher()
        matches = watcher.scan_file(tmp_path / "nonexistent.py")
        assert matches == []
