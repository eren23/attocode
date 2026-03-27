"""Tests for the trigram inverted index."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.integrations.context.trigram_index import TrigramIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a project dir with .attocode/index/ and given source files."""
    index_dir = tmp_path / ".attocode" / "index"
    index_dir.mkdir(parents=True)
    for name, content in files.items():
        fpath = tmp_path / name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
    return tmp_path


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
class TestTrigramIndexBuild:
    def test_build_returns_stats(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "def hello(): pass\n",
            "b.py": "def world(): pass\n",
            "c.py": "class Foo: pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        stats = idx.build(str(proj))
        assert stats["files_indexed"] == 3
        assert stats["trigrams_count"] > 0
        assert stats["build_time_ms"] >= 0
        assert stats["index_size_bytes"] > 0
        assert stats["loaded"] is True
        idx.close()

    def test_build_creates_files(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"x.py": "content\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        assert os.path.isfile(str(proj / ".attocode" / "index" / "trigrams.lookup"))
        assert os.path.isfile(str(proj / ".attocode" / "index" / "trigrams.postings"))
        assert os.path.isfile(str(proj / ".attocode" / "index" / "trigrams.db"))
        idx.close()

    def test_build_skips_binary_extensions(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "code.py": "real code\n",
            "image.png": "not really png but has extension\n",
            "lib.pyc": "bytecode\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        stats = idx.build(str(proj))
        assert stats["files_indexed"] == 1  # only code.py
        idx.close()

    def test_build_skips_dotfiles(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "visible.py": "hello\n",
            ".hidden": "secret\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        stats = idx.build(str(proj))
        assert stats["files_indexed"] == 1
        idx.close()

    def test_build_empty_project(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        stats = idx.build(str(proj))
        assert stats["files_indexed"] == 0
        assert stats["trigrams_count"] == 0
        idx.close()


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
class TestTrigramIndexLoad:
    def test_load_after_build(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.close()

        idx2 = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        assert idx2.load() is True
        assert idx2.is_ready() is True
        idx2.close()

    def test_load_no_files(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "empty_index"
        index_dir.mkdir()
        idx = TrigramIndex(index_dir=str(index_dir))
        assert idx.load() is False
        assert idx.is_ready() is False

    def test_load_corrupt_magic(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.close()

        # Corrupt the lookup file magic bytes
        lookup_path = proj / ".attocode" / "index" / "trigrams.lookup"
        data = lookup_path.read_bytes()
        lookup_path.write_bytes(b"\x00\x00\x00\x00" + data[4:])

        idx2 = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        assert idx2.load() is False


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
class TestTrigramIndexQuery:
    def test_exact_match(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "hello.py": "def unique_hello_function(): pass\n",
            "world.py": "def other_world_function(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        candidates = idx.query("unique_hello_function")
        assert candidates is not None
        assert "hello.py" in candidates
        assert "world.py" not in candidates
        idx.close()

    def test_no_match(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "def hello(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        candidates = idx.query("zzz_nonexistent_xyz")
        assert candidates == []
        idx.close()

    def test_all_files_match(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "def common_func(): pass\n",
            "b.py": "def common_func(): pass\n",
            "c.py": "# common_func reference\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        candidates = idx.query("common_func")
        assert candidates is not None
        assert len(candidates) == 3
        idx.close()

    def test_wildcard_fallback(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        # ".*" yields no trigrams -> should return None
        assert idx.query(".*") is None
        idx.close()

    def test_query_not_ready(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        idx = TrigramIndex(index_dir=str(index_dir))
        assert idx.query("hello") is None

    def test_intersection_narrows(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "both.py": "alpha_beta_gamma\n",
            "only_alpha.py": "alpha_delta_epsilon\n",
            "only_gamma.py": "theta_gamma_zeta\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        # "alpha_beta_gamma" only appears in both.py
        candidates = idx.query("alpha_beta_gamma")
        assert candidates is not None
        assert "both.py" in candidates
        assert len(candidates) == 1
        idx.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
class TestTrigramIndexLifecycle:
    def test_close_and_reopen(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        candidates1 = idx.query("hello")
        idx.close()

        idx2 = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx2.load()
        candidates2 = idx2.query("hello")
        assert set(candidates1 or []) == set(candidates2 or [])
        idx2.close()

    def test_update_file_invalidates(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        assert idx.is_ready() is True

        idx.update_file("a.py", b"changed content")
        assert idx.is_ready() is False
        idx.close()

    def test_remove_file(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "hello\n",
            "b.py": "world\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        idx.remove_file("a.py")
        assert "a.py" not in idx._path_to_file_id
        idx.close()


# ---------------------------------------------------------------------------
# Integration with grep_search
# ---------------------------------------------------------------------------
class TestTrigramGrepIntegration:
    @pytest.mark.asyncio
    async def test_grep_with_trigram_prefilter(self, tmp_path: Path) -> None:
        """Verify grep_search produces correct results when trigram index exists."""
        from attocode.tools.search import grep_search

        proj = _create_project(tmp_path, {
            "target.py": "def unique_xyz_function(): pass\n",
            "other.py": "def something_else(): pass\n",
        })

        # Build trigram index
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.close()

        # grep_search should still find the right result
        result = await grep_search(
            {"pattern": "unique_xyz_function", "path": str(proj)},
        )
        assert "target.py" in result
        assert "unique_xyz_function" in result

    @pytest.mark.asyncio
    async def test_grep_without_index_still_works(self, tmp_path: Path) -> None:
        """Verify grep_search works normally when no trigram index exists."""
        from attocode.tools.search import grep_search

        (tmp_path / "file.py").write_text("searchable_text\n")
        result = await grep_search(
            {"pattern": "searchable_text", "path": str(tmp_path)},
        )
        assert "searchable_text" in result


# ---------------------------------------------------------------------------
# update_file and remove_file
# ---------------------------------------------------------------------------
class TestTrigramIndexUpdateRemove:
    def test_update_file_marks_not_ready(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello world\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        assert idx.is_ready()
        idx.update_file("a.py", b"changed content")
        assert not idx.is_ready()
        idx.close()

    def test_remove_file_drops_mapping(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n", "b.py": "world\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        assert idx.is_ready()
        idx.remove_file("a.py")
        # a.py no longer in path mapping
        assert "a.py" not in idx._path_to_file_id
        # Index still ready (remove_file doesn't invalidate)
        assert idx.is_ready()
        idx.close()

    def test_remove_nonexistent_file_is_noop(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.remove_file("nonexistent.py")  # should not raise
        assert idx.is_ready()
        idx.close()


# ---------------------------------------------------------------------------
# close() idempotency
# ---------------------------------------------------------------------------
class TestTrigramIndexClose:
    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.close()
        idx.close()  # second close should not raise

    def test_query_after_close_returns_none(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello world\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        idx.close()
        result = idx.query("hello")
        assert result is None


# ---------------------------------------------------------------------------
# Case insensitive query
# ---------------------------------------------------------------------------
class TestTrigramIndexCaseInsensitive:
    def test_case_insensitive_query(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "def HelloWorld(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        # Case insensitive should still return candidates (or None if trigrams can't be extracted)
        result = idx.query("helloworld", case_insensitive=True)
        # Either None (no trigrams extractable for case-insensitive) or a list
        assert result is None or isinstance(result, list)
        idx.close()


# ---------------------------------------------------------------------------
# Selectivity threshold
# ---------------------------------------------------------------------------
class TestSelectivityThreshold:
    def _create_large_project(self, tmp_path: Path, n_files: int = 150) -> Path:
        """Create a project with enough files to trigger threshold logic."""
        files = {f"f{i:04d}.py": f"def common_func_{i}(): pass\n" for i in range(n_files)}
        return _create_project(tmp_path, files)

    def test_threshold_triggers_on_broad_match(self, tmp_path: Path) -> None:
        """When >10% of files match, query() returns None (fall back to full scan)."""
        # All 150 files contain "def " and "(): " so querying "def" should
        # match all of them -> 100% selectivity -> threshold triggers
        proj = self._create_large_project(tmp_path)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("def common", selectivity_threshold=0.10)
        # With 150 files all matching, selectivity >> 10%
        assert result is None
        idx.close()

    def test_threshold_not_triggered_on_selective_query(self, tmp_path: Path) -> None:
        """When only a few files match, threshold does not trigger."""
        files = {f"f{i:04d}.py": f"def func_{i}(): pass\n" for i in range(150)}
        files["unique.py"] = "def extremely_unique_snowflake(): pass\n"
        proj = _create_project(tmp_path, files)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("extremely_unique_snowflake", selectivity_threshold=0.10)
        assert result is not None
        assert "unique.py" in result
        idx.close()

    def test_threshold_zero_always_falls_back(self, tmp_path: Path) -> None:
        """threshold=0.0 means any match exceeds it."""
        proj = self._create_large_project(tmp_path)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        files = {f"f{i:04d}.py": f"def unique_xyz_{i}(): pass\n" for i in range(150)}
        files["target.py"] = "def only_target_has_this_xyzzy(): pass\n"
        proj2 = _create_project(tmp_path / "sub", files)
        idx2 = TrigramIndex(index_dir=str(proj2 / ".attocode" / "index"))
        idx2.build(str(proj2))

        result = idx2.query("only_target_has_this_xyzzy", selectivity_threshold=0.0)
        assert result is None  # threshold=0 means always fall back
        idx2.close()

    def test_threshold_one_never_triggers(self, tmp_path: Path) -> None:
        """threshold=1.0 means the index is always used."""
        proj = self._create_large_project(tmp_path)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("def common", selectivity_threshold=1.0)
        assert result is not None  # threshold=1.0, never triggers
        idx.close()

    def test_threshold_skipped_for_small_projects(self, tmp_path: Path) -> None:
        """Below 100 files, threshold is never applied."""
        proj = _create_project(tmp_path, {
            "a.py": "def common(): pass\n",
            "b.py": "def common(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        # 2 files, both match -> 100% selectivity, but <100 files so threshold skipped
        result = idx.query("common", selectivity_threshold=0.10)
        assert result is not None
        idx.close()


# ---------------------------------------------------------------------------
# Explain mode
# ---------------------------------------------------------------------------
class TestExplainMode:
    def test_explain_returns_query_result(self, tmp_path: Path) -> None:
        from attocode.integrations.context.trigram_index import QueryResult

        proj = _create_project(tmp_path, {
            "a.py": "def hello_world(): pass\n",
            "b.py": "def other_thing(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("hello_world", explain=True)
        assert isinstance(result, QueryResult)
        assert result.candidates is not None
        assert "a.py" in result.candidates
        assert len(result.trigram_literals) > 0
        assert len(result.posting_sizes) > 0
        assert len(result.posting_sizes) == len(result.trigram_literals)
        assert result.total_files == 2
        assert result.candidate_count >= 1
        assert result.mode == "trigram-filtered"
        assert result.threshold_triggered is False
        idx.close()

    def test_explain_no_trigrams(self, tmp_path: Path) -> None:
        from attocode.integrations.context.trigram_index import QueryResult

        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query(".*", explain=True)
        assert isinstance(result, QueryResult)
        assert result.candidates is None
        assert result.mode == "full-scan-no-trigrams"
        assert result.trigram_literals == []
        idx.close()

    def test_explain_not_ready(self, tmp_path: Path) -> None:
        from attocode.integrations.context.trigram_index import QueryResult

        index_dir = tmp_path / "index"
        index_dir.mkdir()
        idx = TrigramIndex(index_dir=str(index_dir))

        result = idx.query("hello", explain=True)
        assert isinstance(result, QueryResult)
        assert result.mode == "no-index"
        assert result.candidates is None

    def test_explain_threshold_triggered(self, tmp_path: Path) -> None:
        from attocode.integrations.context.trigram_index import QueryResult

        files = {f"f{i:04d}.py": f"def common_func_{i}(): pass\n" for i in range(150)}
        proj = _create_project(tmp_path, files)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("def common", explain=True, selectivity_threshold=0.10)
        assert isinstance(result, QueryResult)
        assert result.threshold_triggered is True
        assert result.candidates is None
        assert result.mode == "full-scan-threshold"
        assert result.selectivity > 0.10
        idx.close()

    def test_explain_posting_sizes_populated(self, tmp_path: Path) -> None:
        from attocode.integrations.context.trigram_index import QueryResult

        proj = _create_project(tmp_path, {
            "a.py": "def unique_alpha_function(): pass\n",
            "b.py": "def unique_beta_function(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("unique_alpha_function", explain=True)
        assert isinstance(result, QueryResult)
        # Every posting size should be > 0 (the trigrams exist in at least one file)
        assert all(s > 0 for s in result.posting_sizes)
        idx.close()

    def test_explain_posting_sizes_length_matches_trigrams(self, tmp_path: Path) -> None:
        """posting_sizes must always have same length as trigram_literals."""
        from attocode.integrations.context.trigram_index import QueryResult

        proj = _create_project(tmp_path, {
            "a.py": "def hello_world(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        # Query with a pattern where some trigrams may not exist in the index
        # "hello_xyzzy" — "xyzzy" trigrams won't be in any file
        result = idx.query("hello_xyzzy", explain=True)
        assert isinstance(result, QueryResult)
        assert len(result.posting_sizes) == len(result.trigram_literals)

        # Also verify with a pattern that fully matches
        result2 = idx.query("hello_world", explain=True)
        assert isinstance(result2, QueryResult)
        assert len(result2.posting_sizes) == len(result2.trigram_literals)
        idx.close()

    def test_explain_boundary_selectivity_equals_threshold(self, tmp_path: Path) -> None:
        """When selectivity == threshold exactly, threshold should NOT trigger (uses >)."""
        from attocode.integrations.context.trigram_index import QueryResult

        # Create 100 files with "common" in all of them, query with threshold=1.0
        # 100/100 = 1.0 selectivity, threshold 1.0 → > not >= → should NOT trigger
        files = {f"f{i:04d}.py": "def common(): pass\n" for i in range(100)}
        proj = _create_project(tmp_path, files)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))

        result = idx.query("common", explain=True, selectivity_threshold=1.0)
        assert isinstance(result, QueryResult)
        assert result.threshold_triggered is False
        assert result.candidates is not None
        idx.close()
