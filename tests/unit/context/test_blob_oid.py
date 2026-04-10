"""Unit tests for the blob_oid helper.

Covers:

- Single-file compute on a git repo → ``git:<sha1>``
- Single-file compute on a non-git dir → ``sha256:<hex>``
- Missing file → ``sha256:missing:<path>``
- Batch mode produces the same hashes as loop-mode
- Cache hits are returned without re-hashing
- is_git_repo on git vs non-git trees
- check_reachability returns the probed-git subset and passes through
  non-git sentinels

Tests don't require network or sentence-transformers. They DO require
``git`` on PATH — without it the git-specific assertions are skipped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess

import pytest

from attocode.integrations.context.blob_oid import (
    BlobOidCache,
    check_reachability,
    compute_blob_oid,
    compute_blob_oids_batch,
    is_git_repo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_HAS_GIT = shutil.which("git") is not None


def _git(*args: str, cwd: str) -> str:
    """Run a git command with the env set so it doesn't fail inside a
    sandbox with no user.name/email configured."""
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, env=env,
    )


@pytest.fixture
def git_repo(tmp_path):
    """A populated git repo with a few committed files."""
    if not _HAS_GIT:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=str(repo))
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("def a():\n    return 1\n")
    (repo / "src" / "b.py").write_text("def b():\n    return 2\n")
    (repo / "README.md").write_text("# Test\n")
    _git("add", ".", cwd=str(repo))
    _git("commit", "-m", "initial", cwd=str(repo))
    return repo


@pytest.fixture
def plain_dir(tmp_path):
    """A directory that is not a git repo."""
    d = tmp_path / "plain"
    d.mkdir()
    (d / "notes.txt").write_text("hello world\n")
    (d / "sub").mkdir()
    (d / "sub" / "config.json").write_text('{"k": "v"}\n')
    return d


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    def test_git_repo_detected(self, git_repo):
        assert is_git_repo(str(git_repo)) is True

    def test_non_git_dir_not_detected(self, plain_dir):
        assert is_git_repo(str(plain_dir)) is False

    def test_missing_dir_not_detected(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert is_git_repo(str(missing)) is False


# ---------------------------------------------------------------------------
# compute_blob_oid — single file
# ---------------------------------------------------------------------------


class TestComputeBlobOidGit:
    def test_git_prefix_when_in_repo(self, git_repo):
        oid = compute_blob_oid("src/a.py", str(git_repo))
        assert oid.startswith("git:")
        # The 'git:' prefix + 40-hex SHA-1 = 44 chars.
        assert len(oid) == 44

    def test_matches_git_hash_object(self, git_repo):
        oid = compute_blob_oid("src/a.py", str(git_repo))
        expected_sha = _git("hash-object", "src/a.py", cwd=str(git_repo)).strip()
        assert oid == f"git:{expected_sha}"

    def test_same_content_same_oid(self, git_repo):
        # Duplicate a file — same content → same git blob OID.
        (git_repo / "src" / "a_copy.py").write_text("def a():\n    return 1\n")
        oid1 = compute_blob_oid("src/a.py", str(git_repo))
        oid2 = compute_blob_oid("src/a_copy.py", str(git_repo))
        assert oid1 == oid2

    def test_different_content_different_oid(self, git_repo):
        oid1 = compute_blob_oid("src/a.py", str(git_repo))
        oid2 = compute_blob_oid("src/b.py", str(git_repo))
        assert oid1 != oid2


class TestComputeBlobOidNonGit:
    def test_sha256_prefix(self, plain_dir):
        oid = compute_blob_oid("notes.txt", str(plain_dir))
        assert oid.startswith("sha256:")
        # "sha256:" + 64-hex = 71 chars.
        assert len(oid) == 71

    def test_sha256_matches_stdlib(self, plain_dir):
        content = (plain_dir / "notes.txt").read_bytes()
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        oid = compute_blob_oid("notes.txt", str(plain_dir))
        assert oid == expected

    def test_missing_file_sentinel(self, plain_dir):
        oid = compute_blob_oid("does_not_exist.md", str(plain_dir))
        assert oid.startswith("sha256:missing:")

    def test_absolute_path_accepted(self, plain_dir):
        abs_path = str(plain_dir / "notes.txt")
        oid_rel = compute_blob_oid("notes.txt", str(plain_dir))
        oid_abs = compute_blob_oid(abs_path, str(plain_dir))
        assert oid_rel == oid_abs


# ---------------------------------------------------------------------------
# compute_blob_oids_batch
# ---------------------------------------------------------------------------


class TestBatchMode:
    def test_git_batch_matches_loop(self, git_repo):
        paths = ["src/a.py", "src/b.py", "README.md"]
        batch = compute_blob_oids_batch(paths, str(git_repo))
        loop = {p: compute_blob_oid(p, str(git_repo)) for p in paths}
        assert batch == loop
        assert all(o.startswith("git:") for o in batch.values())

    def test_non_git_batch_matches_loop(self, plain_dir):
        paths = ["notes.txt", "sub/config.json"]
        batch = compute_blob_oids_batch(paths, str(plain_dir))
        loop = {p: compute_blob_oid(p, str(plain_dir)) for p in paths}
        assert batch == loop
        assert all(o.startswith("sha256:") for o in batch.values())

    def test_batch_with_missing_file(self, git_repo):
        paths = ["src/a.py", "does_not_exist.md"]
        result = compute_blob_oids_batch(paths, str(git_repo))
        assert result["src/a.py"].startswith("git:")
        assert result["does_not_exist.md"].startswith("sha256:missing:")

    def test_empty_batch_returns_empty(self, git_repo):
        assert compute_blob_oids_batch([], str(git_repo)) == {}


# ---------------------------------------------------------------------------
# BlobOidCache
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_hit_returns_without_recompute(self, git_repo):
        cache = BlobOidCache(project_dir=str(git_repo))
        try:
            oid1 = compute_blob_oid("src/a.py", str(git_repo), cache=cache)
            # Second call should hit the cache (we can't easily verify
            # "no subprocess was spawned" from Python, but a correct
            # cache at least returns the same value).
            oid2 = compute_blob_oid("src/a.py", str(git_repo), cache=cache)
            assert oid1 == oid2
            # Cache row exists.
            row = cache.get("src/a.py", os.stat(git_repo / "src/a.py").st_mtime,
                            os.stat(git_repo / "src/a.py").st_size)
            assert row == oid1
        finally:
            cache.close()

    def test_cache_miss_on_mtime_change(self, git_repo):
        cache = BlobOidCache(project_dir=str(git_repo))
        try:
            oid1 = compute_blob_oid("src/a.py", str(git_repo), cache=cache)
            # Rewrite with different content → different mtime + different oid.
            (git_repo / "src" / "a.py").write_text("def a():\n    return 999\n")
            oid2 = compute_blob_oid("src/a.py", str(git_repo), cache=cache)
            assert oid1 != oid2
        finally:
            cache.close()

    def test_batch_populates_cache(self, git_repo):
        cache = BlobOidCache(project_dir=str(git_repo))
        try:
            compute_blob_oids_batch(
                ["src/a.py", "src/b.py"], str(git_repo), cache=cache,
            )
            # Both should now be queryable.
            for rel in ("src/a.py", "src/b.py"):
                stat = os.stat(git_repo / rel)
                cached = cache.get(rel, stat.st_mtime, stat.st_size)
                assert cached is not None
                assert cached.startswith("git:")
        finally:
            cache.close()

    def test_clear(self, git_repo):
        cache = BlobOidCache(project_dir=str(git_repo))
        try:
            compute_blob_oid("src/a.py", str(git_repo), cache=cache)
            # clear() should return at least 1 row removed.
            n = cache.clear()
            assert n >= 1
        finally:
            cache.close()


# ---------------------------------------------------------------------------
# check_reachability
# ---------------------------------------------------------------------------


class TestReachability:
    def test_reachable_committed_blobs(self, git_repo):
        a_oid = compute_blob_oid("src/a.py", str(git_repo))
        b_oid = compute_blob_oid("src/b.py", str(git_repo))
        reachable = check_reachability({a_oid, b_oid}, str(git_repo))
        assert a_oid in reachable
        assert b_oid in reachable

    def test_unreachable_fake_blob(self, git_repo):
        fake = "git:" + "0" * 40  # zero-hash blob doesn't exist
        reachable = check_reachability({fake}, str(git_repo))
        assert fake not in reachable

    def test_non_git_oids_passthrough(self, git_repo):
        """sha256: anchors can't be probed by git — pass them through."""
        sha = "sha256:" + "a" * 64
        reachable = check_reachability({sha}, str(git_repo))
        assert sha in reachable

    def test_empty_input_returns_empty(self, git_repo):
        assert check_reachability(set(), str(git_repo)) == set()

    def test_non_git_project_passes_everything(self, plain_dir):
        """Without git, everything passes through as 'reachable'."""
        anchors = {
            "git:" + "a" * 40,
            "sha256:" + "b" * 64,
        }
        reachable = check_reachability(anchors, str(plain_dir))
        assert reachable == anchors
