"""Tests for preseed map caching."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _init_git_repo(tmp_path: Path) -> None:
    """Create a minimal git repo with one commit.

    Includes a ``.gitignore`` for ``.attocode/`` so the cache file
    written by ``_get_or_build_preseed`` does not alter the dirty
    fingerprint.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / ".gitignore").write_text(".attocode/\n")
    (tmp_path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True, check=True,
    )


def test_git_fingerprint_includes_head_and_dirty():
    """Fingerprint format is HEAD:dirty_hash."""
    from attocode.agent.run_context_builder import _get_git_fingerprint

    fp = _get_git_fingerprint(".")
    # May be None if not in a git repo, but in CI this project is a git repo
    if fp is None:
        pytest.skip("not inside a git repository")
    assert ":" in fp  # HEAD:dirty_hash format
    parts = fp.split(":")
    assert len(parts[0]) == 40  # Full SHA
    assert len(parts[1]) == 12  # Truncated dirty hash


def test_git_fingerprint_changes_on_edit(tmp_path):
    """Fingerprint changes when a file is modified."""
    from attocode.agent.run_context_builder import _get_git_fingerprint

    _init_git_repo(tmp_path)

    fp1 = _get_git_fingerprint(str(tmp_path))
    assert fp1 is not None

    # Modify a file (uncommitted)
    (tmp_path / "file.txt").write_text("world")
    fp2 = _get_git_fingerprint(str(tmp_path))
    assert fp2 is not None

    assert fp1 != fp2  # Dirty state changed


def test_git_fingerprint_stable_when_unchanged(tmp_path):
    """Same repo state produces same fingerprint."""
    from attocode.agent.run_context_builder import _get_git_fingerprint

    _init_git_repo(tmp_path)

    fp1 = _get_git_fingerprint(str(tmp_path))
    fp2 = _get_git_fingerprint(str(tmp_path))
    assert fp1 == fp2


def test_git_fingerprint_returns_none_outside_repo(tmp_path):
    """Non-git directory returns None."""
    from attocode.agent.run_context_builder import _get_git_fingerprint

    fp = _get_git_fingerprint(str(tmp_path))
    assert fp is None


def _make_mock_preseed_map():
    """Create a mock repo-map object with the expected attributes."""
    mock_map = MagicMock()
    mock_map.total_files = 10
    mock_map.total_lines = 500
    mock_map.languages = {"python": 8, "yaml": 2}
    mock_map.tree = "src/\n  main.py"
    mock_map.symbols = {"src/main.py": ["main", "run"]}
    return mock_map


def test_preseed_cache_hit(tmp_path):
    """Second call with same fingerprint returns cached content."""
    from attocode.agent.run_context_builder import _get_or_build_preseed

    mock_map = _make_mock_preseed_map()
    cbc = MagicMock()
    cbc.get_preseed_map.return_value = mock_map

    _init_git_repo(tmp_path)

    # First call -- builds
    content1 = _get_or_build_preseed(cbc, str(tmp_path))
    assert content1 is not None
    assert cbc.get_preseed_map.call_count == 1

    # Second call -- cache hit
    content2 = _get_or_build_preseed(cbc, str(tmp_path))
    assert content2 == content1
    assert cbc.get_preseed_map.call_count == 1  # NOT called again


def test_preseed_cache_miss_on_edit(tmp_path):
    """Cache misses when a file is edited."""
    from attocode.agent.run_context_builder import _get_or_build_preseed

    mock_map = _make_mock_preseed_map()
    cbc = MagicMock()
    cbc.get_preseed_map.return_value = mock_map

    _init_git_repo(tmp_path)

    _get_or_build_preseed(cbc, str(tmp_path))
    assert cbc.get_preseed_map.call_count == 1

    # Edit a file (uncommitted)
    (tmp_path / "file.txt").write_text("v2")
    _get_or_build_preseed(cbc, str(tmp_path))
    assert cbc.get_preseed_map.call_count == 2  # Rebuilt due to dirty change


def test_preseed_cache_content_includes_tree(tmp_path):
    """Cached content includes the tree and symbols from the repo map."""
    from attocode.agent.run_context_builder import _get_or_build_preseed

    mock_map = _make_mock_preseed_map()
    cbc = MagicMock()
    cbc.get_preseed_map.return_value = mock_map

    _init_git_repo(tmp_path)

    content = _get_or_build_preseed(cbc, str(tmp_path))
    assert content is not None
    assert "src/" in content
    assert "main.py" in content
    assert "python" in content
    assert "Files: 10" in content


def test_preseed_cache_writes_json_file(tmp_path):
    """Cache file is written to .attocode/cache/preseed_map.json."""
    from attocode.agent.run_context_builder import _get_or_build_preseed

    mock_map = _make_mock_preseed_map()
    cbc = MagicMock()
    cbc.get_preseed_map.return_value = mock_map

    _init_git_repo(tmp_path)

    _get_or_build_preseed(cbc, str(tmp_path))

    cache_file = tmp_path / ".attocode" / "cache" / "preseed_map.json"
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "fingerprint" in data
    assert "content" in data


def test_preseed_no_git_still_builds(tmp_path):
    """Without git, preseed still builds (just no caching)."""
    from attocode.agent.run_context_builder import _get_or_build_preseed

    mock_map = _make_mock_preseed_map()
    cbc = MagicMock()
    cbc.get_preseed_map.return_value = mock_map

    # No git init -- tmp_path is not a git repo
    content = _get_or_build_preseed(cbc, str(tmp_path))
    assert content is not None
    assert cbc.get_preseed_map.call_count == 1

    # No cache file written (fingerprint was None)
    cache_file = tmp_path / ".attocode" / "cache" / "preseed_map.json"
    assert not cache_file.exists()
