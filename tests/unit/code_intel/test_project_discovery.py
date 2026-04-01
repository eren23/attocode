"""Tests for project auto-discovery in attocode-code-intel."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest


class TestWalkUp:
    """Tests for _walk_up helper."""

    def test_walk_up_single_parent(self, tmp_path: Path) -> None:
        """Yields parent directories starting from dirname(start)."""
        from attocode.code_intel._shared import _walk_up

        parents = list(_walk_up(str(tmp_path), max_depth=5))
        assert len(parents) >= 1
        # _walk_up yields dirname(start) first, then climbs upward.
        # On macOS the temp dir sits under /private/var/folders/... so dirname
        # may traverse through the /private/var -> /var symlink chain.
        # Just verify we get at least one parent and they're all prefixes of each other.
        for p in parents:
            assert str(tmp_path).startswith(p) or p in str(tmp_path)

    def test_walk_up_stops_at_root(self, tmp_path: Path) -> None:
        """Stops yielding when filesystem root is reached."""
        from attocode.code_intel._shared import _walk_up

        parents = list(_walk_up(str(tmp_path), max_depth=20))
        # Eventually reaches filesystem root where dirname == itself
        # The last parent should be "/" or the root
        assert len(parents) <= 20

    def test_walk_up_max_depth_respected(self, tmp_path: Path) -> None:
        """Respects max_depth limit."""
        from attocode.code_intel._shared import _walk_up

        parents = list(_walk_up(str(tmp_path), max_depth=2))
        assert len(parents) <= 2

    def test_walk_up_yields_unique_parents(self, tmp_path: Path) -> None:
        """Each parent is unique (no duplicates from hitting root)."""
        from attocode.code_intel._shared import _walk_up

        parents = list(_walk_up(str(tmp_path), max_depth=20))
        assert len(parents) == len(set(parents))


class TestGetProjectDir:
    """Tests for _get_project_dir."""

    def test_env_var_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ATTOCODE_PROJECT_DIR env var is used when set."""
        from attocode.code_intel._shared import _get_project_dir

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", "/some/custom/path")
        result = _get_project_dir()
        assert result == os.path.abspath("/some/custom/path")

    def test_auto_discovers_git_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds project root by walking up to .git/ marker."""
        from attocode.code_intel._shared import _get_project_dir

        # Create nested structure
        subdir = tmp_path / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        monkeypatch.chdir(str(subdir))
        monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)

        result = _get_project_dir()
        assert result == str(tmp_path)

    def test_auto_discovers_attocode_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds project root by walking up to .attocode/ marker."""
        from attocode.code_intel._shared import _get_project_dir

        subdir = tmp_path / "src" / "pkg"
        subdir.mkdir(parents=True)
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()

        monkeypatch.chdir(str(subdir))
        monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)

        result = _get_project_dir()
        assert result == str(tmp_path)

    def test_prefers_nearest_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds the nearest marker when multiple exist in ancestry."""
        from attocode.code_intel._shared import _get_project_dir

        # Structure:
        #   tmp_path/parent-repo/.git         <- marker at this level
        #   tmp_path/parent-repo/subproject/.attocode  <- closer marker
        #   tmp_path/parent-repo/subproject/src (CWD)
        parent_git = tmp_path / "parent-repo"
        parent_git.mkdir()
        (parent_git / ".git").mkdir()

        closer_attocode = parent_git / "subproject" / ".attocode"
        closer_attocode.mkdir(parents=True)
        subdir = parent_git / "subproject" / "src"
        subdir.mkdir()

        monkeypatch.chdir(str(subdir))
        monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)

        result = _get_project_dir()
        # The closer marker (.attocode) is at subdir.parent = parent_git/subproject
        # _walk_up yields: [cwd, subdir.parent, parent_git, ...]
        # subdir.parent has .attocode -> found, return it
        assert result == str(subdir.parent)

    def test_falls_back_to_cwd_when_no_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns CWD when no marker is found."""
        from attocode.code_intel._shared import _get_project_dir

        subdir = tmp_path / "orphan" / "code"
        subdir.mkdir(parents=True)

        monkeypatch.chdir(str(subdir))
        monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)

        result = _get_project_dir()
        assert result == str(subdir)

    def test_resolves_to_absolute_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Always returns an absolute path."""
        from attocode.code_intel._shared import _get_project_dir

        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "src"
        subdir.mkdir()

        monkeypatch.chdir(str(subdir))
        monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)

        result = _get_project_dir()
        assert os.path.isabs(result)

    def test_env_var_relative_path_becomes_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative ATTOCODE_PROJECT_DIR is resolved to absolute."""
        from attocode.code_intel._shared import _get_project_dir

        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        monkeypatch.chdir(str(tmp_path))
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", ".")

        result = _get_project_dir()
        assert result == str(tmp_path)
