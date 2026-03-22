"""Tests for ThemeWatcher hot-reload functionality."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attocode.tui.theme import ThemeWatcher


class TestThemeWatcherInit:
    """Test ThemeWatcher construction and properties."""

    def test_default_poll_interval(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None)
        assert watcher._poll_interval == ThemeWatcher.DEFAULT_POLL_INTERVAL

    def test_custom_poll_interval(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None, poll_interval=5.0)
        assert watcher._poll_interval == 5.0

    def test_watch_paths_empty_by_default(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None)
        assert watcher.watch_paths == []

    def test_watch_paths_copied(self) -> None:
        paths = [Path("/tmp/a.tcss")]
        watcher = ThemeWatcher(callback=lambda: None, watch_paths=paths)
        # Mutating the original list should not affect the watcher.
        paths.append(Path("/tmp/b.tcss"))
        assert len(watcher.watch_paths) == 1

    def test_not_running_initially(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None)
        assert not watcher.is_running


class TestThemeWatcherStartStop:
    """Test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None, poll_interval=10.0)
        await watcher.start()
        assert watcher.is_running
        await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None, poll_interval=10.0)
        await watcher.start()
        await watcher.stop()
        assert not watcher.is_running

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None, poll_interval=10.0)
        await watcher.start()
        await watcher.start()  # Should not raise or create a second task.
        assert watcher.is_running
        await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None)
        await watcher.stop()  # Should not raise.
        assert not watcher.is_running


class TestThemeWatcherDetection:
    """Test file change detection logic."""

    @pytest.mark.asyncio
    async def test_detects_file_modification(self, tmp_path: Path) -> None:
        css_file = tmp_path / "test.tcss"
        css_file.write_text("Screen { background: red; }")

        callback_count = 0

        def on_change() -> None:
            nonlocal callback_count
            callback_count += 1

        watcher = ThemeWatcher(
            callback=on_change,
            watch_paths=[css_file],
            poll_interval=0.05,
        )
        await watcher.start()

        # Give the watcher one poll cycle to snapshot initial mtimes.
        await asyncio.sleep(0.1)

        # Modify the file.
        css_file.write_text("Screen { background: blue; }")

        # Wait for the watcher to detect the change.
        await asyncio.sleep(0.2)
        await watcher.stop()

        assert callback_count >= 1

    @pytest.mark.asyncio
    async def test_no_callback_without_change(self, tmp_path: Path) -> None:
        css_file = tmp_path / "test.tcss"
        css_file.write_text("Screen { background: red; }")

        callback_count = 0

        def on_change() -> None:
            nonlocal callback_count
            callback_count += 1

        watcher = ThemeWatcher(
            callback=on_change,
            watch_paths=[css_file],
            poll_interval=0.05,
        )
        await watcher.start()
        await asyncio.sleep(0.2)
        await watcher.stop()

        assert callback_count == 0

    @pytest.mark.asyncio
    async def test_handles_missing_file_gracefully(self) -> None:
        missing = Path("/tmp/nonexistent_theme_file_abc123.tcss")
        watcher = ThemeWatcher(
            callback=lambda: None,
            watch_paths=[missing],
            poll_interval=0.05,
        )
        await watcher.start()
        await asyncio.sleep(0.1)
        await watcher.stop()
        # Should not raise — missing files are silently skipped.

    @pytest.mark.asyncio
    async def test_detects_file_removal(self, tmp_path: Path) -> None:
        css_file = tmp_path / "test.tcss"
        css_file.write_text("Screen { background: red; }")

        callback_count = 0

        def on_change() -> None:
            nonlocal callback_count
            callback_count += 1

        watcher = ThemeWatcher(
            callback=on_change,
            watch_paths=[css_file],
            poll_interval=0.05,
        )
        await watcher.start()
        await asyncio.sleep(0.1)

        # Remove the file.
        css_file.unlink()

        await asyncio.sleep(0.2)
        await watcher.stop()

        assert callback_count >= 1

    @pytest.mark.asyncio
    async def test_callback_error_does_not_stop_watcher(self, tmp_path: Path) -> None:
        css_file = tmp_path / "test.tcss"
        css_file.write_text("Screen { background: red; }")

        call_count = 0

        def bad_callback() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("callback boom")

        watcher = ThemeWatcher(
            callback=bad_callback,
            watch_paths=[css_file],
            poll_interval=0.05,
        )
        await watcher.start()
        await asyncio.sleep(0.1)

        # First modification — callback raises but watcher should survive.
        css_file.write_text("Screen { background: blue; }")
        await asyncio.sleep(0.2)

        # Second modification — watcher should still be running.
        css_file.write_text("Screen { background: green; }")
        await asyncio.sleep(0.2)

        await watcher.stop()

        assert call_count >= 2
        assert not watcher.is_running


class TestThemeWatcherCheckForChanges:
    """Test the internal _check_for_changes method directly."""

    def test_no_paths_returns_false(self) -> None:
        watcher = ThemeWatcher(callback=lambda: None)
        watcher._snapshot_mtimes()
        assert watcher._check_for_changes() is False

    def test_unchanged_file_returns_false(self, tmp_path: Path) -> None:
        css_file = tmp_path / "test.tcss"
        css_file.write_text("body { }")

        watcher = ThemeWatcher(callback=lambda: None, watch_paths=[css_file])
        watcher._snapshot_mtimes()
        assert watcher._check_for_changes() is False

    def test_modified_file_returns_true(self, tmp_path: Path) -> None:
        import os
        import time

        css_file = tmp_path / "test.tcss"
        css_file.write_text("body { }")

        watcher = ThemeWatcher(callback=lambda: None, watch_paths=[css_file])
        watcher._snapshot_mtimes()

        # Ensure mtime actually changes (some filesystems have 1s resolution).
        time.sleep(0.05)
        css_file.write_text("body { color: red; }")
        # Force mtime update if filesystem resolution is coarse.
        os.utime(css_file, (time.time() + 1, time.time() + 1))

        assert watcher._check_for_changes() is True
