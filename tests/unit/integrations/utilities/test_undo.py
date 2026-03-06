"""Tests for undo system."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.utilities.undo import FileChange, FileChangeTracker


class TestFileChange:
    def test_was_created(self) -> None:
        change = FileChange(
            path="/tmp/f.py",
            before_content=None,
            after_content="hello",
            tool_name="write_file",
            timestamp=1.0,
        )
        assert change.was_created
        assert not change.was_deleted
        assert not change.was_modified
        assert change.change_type == "created"

    def test_was_deleted(self) -> None:
        change = FileChange(
            path="/tmp/f.py",
            before_content="hello",
            after_content=None,
            tool_name="delete_file",
            timestamp=1.0,
        )
        assert change.was_deleted
        assert not change.was_created
        assert not change.was_modified
        assert change.change_type == "deleted"

    def test_was_modified(self) -> None:
        change = FileChange(
            path="/tmp/f.py",
            before_content="old",
            after_content="new",
            tool_name="edit_file",
            timestamp=1.0,
        )
        assert change.was_modified
        assert not change.was_created
        assert not change.was_deleted
        assert change.change_type == "modified"

    def test_defaults(self) -> None:
        change = FileChange(
            path="/tmp/f.py",
            before_content="a",
            after_content="b",
            tool_name="edit_file",
            timestamp=1.0,
        )
        assert change.iteration == 0
        assert change.description == ""
        assert not change.undone


class TestTrackChange:
    def test_basic_tracking(self) -> None:
        tracker = FileChangeTracker()
        change = tracker.track_change(
            path="/tmp/foo.py",
            before_content="old",
            after_content="new",
            tool_name="edit_file",
        )
        assert change.was_modified
        assert len(tracker.changes) == 1

    def test_resolves_path(self, tmp_path: Path) -> None:
        tracker = FileChangeTracker()
        relpath = str(tmp_path / "subdir" / ".." / "file.py")
        change = tracker.track_change(
            path=relpath,
            before_content=None,
            after_content="content",
            tool_name="write_file",
        )
        # Path should be resolved (no ".." components)
        assert ".." not in change.path

    def test_records_iteration(self) -> None:
        tracker = FileChangeTracker()
        tracker.set_turn(5)
        change = tracker.track_change(
            path="/tmp/f.py",
            before_content="a",
            after_content="b",
            tool_name="edit_file",
        )
        assert change.iteration == 5

    def test_records_description(self) -> None:
        tracker = FileChangeTracker()
        change = tracker.track_change(
            path="/tmp/f.py",
            before_content="a",
            after_content="b",
            tool_name="edit_file",
            description="Fixed import order",
        )
        assert change.description == "Fixed import order"


class TestTrackFileBeforeWrite:
    def test_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.py"
        target.write_text("original content", encoding="utf-8")

        tracker = FileChangeTracker()
        content = tracker.track_file_before_write(str(target))
        assert content == "original content"

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        tracker = FileChangeTracker()
        content = tracker.track_file_before_write(str(tmp_path / "missing.py"))
        assert content is None

    def test_directory_returns_none(self, tmp_path: Path) -> None:
        tracker = FileChangeTracker()
        content = tracker.track_file_before_write(str(tmp_path))
        assert content is None


class TestUndoLastChange:
    def test_undo_modification(self, tmp_path: Path) -> None:
        target = tmp_path / "file.py"
        target.write_text("original", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.track_change(
            path=str(target),
            before_content="original",
            after_content="modified",
            tool_name="edit_file",
        )
        # Overwrite with new content to simulate the edit
        target.write_text("modified", encoding="utf-8")

        result = tracker.undo_last_change()
        assert "Reverted" in result
        assert target.read_text(encoding="utf-8") == "original"

    def test_undo_creation(self, tmp_path: Path) -> None:
        target = tmp_path / "new_file.py"
        target.write_text("content", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.track_change(
            path=str(target),
            before_content=None,
            after_content="content",
            tool_name="write_file",
        )

        result = tracker.undo_last_change()
        assert "creation" in result.lower()
        assert not target.exists()

    def test_undo_deletion(self, tmp_path: Path) -> None:
        target = tmp_path / "deleted.py"

        tracker = FileChangeTracker()
        tracker.track_change(
            path=str(target),
            before_content="old data",
            after_content=None,
            tool_name="delete_file",
        )

        result = tracker.undo_last_change()
        assert "Restored" in result
        assert target.read_text(encoding="utf-8") == "old data"

    def test_undo_no_changes(self) -> None:
        tracker = FileChangeTracker()
        result = tracker.undo_last_change()
        assert "No changes to undo" in result

    def test_skips_already_undone(self, tmp_path: Path) -> None:
        target = tmp_path / "f.py"
        target.write_text("v1", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.track_change(
            path=str(target),
            before_content="v0",
            after_content="v1",
            tool_name="edit_file",
        )
        tracker.track_change(
            path=str(target),
            before_content="v1",
            after_content="v2",
            tool_name="edit_file",
        )
        target.write_text("v2", encoding="utf-8")

        # Undo v2 -> v1
        tracker.undo_last_change()
        assert target.read_text(encoding="utf-8") == "v1"

        # Undo v1 -> v0
        tracker.undo_last_change()
        assert target.read_text(encoding="utf-8") == "v0"


class TestUndoCurrentTurn:
    def test_undoes_all_turn_changes(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("modified_a", encoding="utf-8")
        f2.write_text("modified_b", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.set_turn(3)
        tracker.track_change(str(f1), "orig_a", "modified_a", "edit_file")
        tracker.track_change(str(f2), "orig_b", "modified_b", "edit_file")

        result = tracker.undo_current_turn()
        assert "Undid 2 changes" in result
        assert f1.read_text(encoding="utf-8") == "orig_a"
        assert f2.read_text(encoding="utf-8") == "orig_b"

    def test_no_changes_in_turn(self) -> None:
        tracker = FileChangeTracker()
        tracker.set_turn(99)
        result = tracker.undo_current_turn()
        assert "No changes" in result


class TestUndoFile:
    def test_undo_specific_file(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("new_a", encoding="utf-8")
        f2.write_text("new_b", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.track_change(str(f1), "old_a", "new_a", "edit_file")
        tracker.track_change(str(f2), "old_b", "new_b", "edit_file")

        result = tracker.undo_file(str(f2))
        assert "Reverted" in result
        assert f2.read_text(encoding="utf-8") == "old_b"
        # f1 should remain unchanged
        assert f1.read_text(encoding="utf-8") == "new_a"

    def test_no_changes_for_file(self) -> None:
        tracker = FileChangeTracker()
        result = tracker.undo_file("/tmp/nonexistent.py")
        assert "No undoable changes" in result


class TestGetFileHistory:
    def test_returns_changes_for_file(self, tmp_path: Path) -> None:
        target = tmp_path / "f.py"
        tracker = FileChangeTracker()
        tracker.track_change(str(target), None, "v1", "write_file")
        tracker.track_change(str(target), "v1", "v2", "edit_file")
        tracker.track_change(str(tmp_path / "other.py"), None, "x", "write_file")

        history = tracker.get_file_history(str(target))
        assert len(history) == 2
        # Newest first
        assert history[0].after_content == "v2"
        assert history[1].after_content == "v1"


class TestGetSessionChanges:
    def test_returns_all_newest_first(self) -> None:
        tracker = FileChangeTracker()
        tracker.track_change("/a", None, "a", "write_file")
        tracker.track_change("/b", None, "b", "write_file")

        changes = tracker.get_session_changes()
        assert len(changes) == 2
        # Newest first
        assert changes[0].path == str(Path("/b").resolve())


class TestMaxHistory:
    def test_trims_old_entries(self) -> None:
        tracker = FileChangeTracker(max_history=5)
        for i in range(10):
            tracker.track_change(f"/tmp/f{i}.py", None, f"v{i}", "write_file")

        assert len(tracker.changes) == 5
        # Should keep the most recent 5
        assert tracker.changes[0].after_content == "v5"


class TestFormatHistory:
    def test_empty(self) -> None:
        tracker = FileChangeTracker()
        output = tracker.format_history()
        assert "No file changes" in output

    def test_shows_entries(self, tmp_path: Path) -> None:
        tracker = FileChangeTracker()
        tracker.track_change(str(tmp_path / "f.py"), None, "x", "write_file")
        output = tracker.format_history()
        assert "created" in output
        assert "write_file" in output
        assert "1 total" in output

    def test_shows_undone_status(self, tmp_path: Path) -> None:
        target = tmp_path / "f.py"
        target.write_text("content", encoding="utf-8")

        tracker = FileChangeTracker()
        tracker.track_change(str(target), None, "content", "write_file")
        tracker.undo_last_change()

        output = tracker.format_history()
        assert "[undone]" in output

    def test_max_entries(self) -> None:
        tracker = FileChangeTracker()
        for i in range(30):
            tracker.track_change(f"/tmp/f{i}.py", None, f"v{i}", "write_file")
        output = tracker.format_history(max_entries=5)
        lines = output.strip().split("\n")
        # 1 header + 5 entries
        assert len(lines) == 6


class TestClear:
    def test_clears_history(self) -> None:
        tracker = FileChangeTracker()
        tracker.track_change("/tmp/f.py", None, "x", "write_file")
        tracker.clear()
        assert tracker.changes == []
