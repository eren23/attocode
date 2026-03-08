"""Tests for attoswarm.protocol.locks — flock-based file locking."""

from __future__ import annotations

import threading
from pathlib import Path

from attoswarm.protocol.locks import locked_file


class TestLockedFile:
    def test_creates_lock_file(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        with locked_file(lock_path):
            assert lock_path.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "sub" / "dir" / "test.lock"
        with locked_file(lock_path):
            assert lock_path.parent.is_dir()

    def test_serializes_access(self, tmp_path: Path) -> None:
        """Two threads competing for the same lock should serialize."""
        lock_path = tmp_path / "race.lock"
        shared = tmp_path / "counter.txt"
        shared.write_text("0")

        def increment() -> None:
            for _ in range(50):
                with locked_file(lock_path):
                    val = int(shared.read_text())
                    shared.write_text(str(val + 1))

        t1 = threading.Thread(target=increment)
        t2 = threading.Thread(target=increment)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert int(shared.read_text()) == 100

    def test_exception_releases_lock(self, tmp_path: Path) -> None:
        """Lock should be released even if body raises."""
        lock_path = tmp_path / "exc.lock"
        try:
            with locked_file(lock_path):
                raise ValueError("boom")
        except ValueError:
            pass

        # Should be able to re-acquire immediately
        with locked_file(lock_path):
            pass  # no deadlock
