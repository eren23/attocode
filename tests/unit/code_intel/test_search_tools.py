"""Tests for fast_search MCP tool — explain mode, selectivity threshold, diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from attocode.integrations.context.trigram_index import QueryResult, TrigramIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(tmp_path: Path, files: dict[str, str]) -> Path:
    index_dir = tmp_path / ".attocode" / "index"
    index_dir.mkdir(parents=True)
    for name, content in files.items():
        fpath = tmp_path / name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
    return tmp_path


def _call_fast_search(proj: Path, idx: TrigramIndex, **kwargs) -> str:
    """Call fast_search() with patched globals so it targets *proj*."""
    from attocode.code_intel.tools import search_tools as st

    with (
        patch.object(st, "_get_project_dir", return_value=str(proj)),
        patch.object(st, "_get_trigram_index", return_value=idx),
    ):
        return st.fast_search(**kwargs)


# ---------------------------------------------------------------------------
# Explain mode (direct fast_search call)
# ---------------------------------------------------------------------------
class TestFastSearchExplain:
    def test_explain_includes_diagnostics_header(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello_world(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern="hello_world", explain=True)
        assert "--- Search Diagnostics ---" in result
        idx.close()

    def test_explain_shows_trigrams(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello_world(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern="hello_world", explain=True)
        assert "Trigrams:" in result
        assert "hel" in result
        idx.close()

    def test_explain_shows_mode_and_selectivity(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern="hello", explain=True)
        assert "Mode:" in result
        assert "trigram-filtered" in result
        assert "Selectivity:" in result
        assert "PASS" in result
        idx.close()

    def test_explain_false_no_diagnostics(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def hello(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern="hello", explain=False)
        assert "--- Search Diagnostics ---" not in result
        idx.close()

    def test_explain_no_trigrams_pattern(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "hello\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern=".*", explain=True)
        assert "full-scan-no-trigrams" in result
        idx.close()


# ---------------------------------------------------------------------------
# Selectivity threshold (direct fast_search call)
# ---------------------------------------------------------------------------
class TestFastSearchBuildFailure:
    def test_explain_when_build_fails_shows_diagnostics(self, tmp_path: Path) -> None:
        """When explain=True and index build fails, diagnostics should still appear."""
        from attocode.code_intel.tools import search_tools as st

        proj = _create_project(tmp_path, {"a.py": "hello world\n"})
        # No index built, _get_trigram_index returns None → triggers auto-build
        # Patch TrigramIndex at the source module so the lazy import inside
        # fast_search picks it up.
        with (
            patch.object(st, "_get_project_dir", return_value=str(proj)),
            patch.object(st, "_get_trigram_index", return_value=None),
            patch(
                "attocode.integrations.context.trigram_index.TrigramIndex",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = st.fast_search(pattern="hello", explain=True)
        assert "--- Search Diagnostics ---" in result
        assert "index-build-failed" in result


class TestFastSearchSelectivity:
    def test_threshold_triggers_on_broad_match(self, tmp_path: Path) -> None:
        files = {f"f{i:04d}.py": f"def common_func_{i}(): pass\n" for i in range(150)}
        proj = _create_project(tmp_path, files)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(
            proj, idx, pattern="def common", selectivity_threshold=0.10, explain=True,
        )
        assert "SKIP (threshold exceeded)" in result
        assert "full-scan-threshold" in result
        idx.close()

    def test_default_threshold_no_interference(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "a.py": "def unique_thing(): pass\n",
            "b.py": "def other(): pass\n",
        })
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        result = _call_fast_search(proj, idx, pattern="unique_thing")
        assert "unique_thing" in result
        idx.close()


# ---------------------------------------------------------------------------
# Diagnostics formatting (via QueryResult directly)
# ---------------------------------------------------------------------------
class TestDiagnosticsFormat:
    def _format(self, qr: QueryResult, pattern: str) -> str:
        """Replicate the diagnostics formatting logic from fast_search."""
        sel_pct = f"{qr.selectivity * 100:.2f}%"
        threshold_pct = f"{qr.threshold * 100:.1f}%"
        verdict = "SKIP (threshold exceeded)" if qr.threshold_triggered else "PASS"
        lines = [
            "",
            "--- Search Diagnostics ---",
            f"Pattern:            {pattern}",
            f"Trigrams:           {qr.trigram_literals!r}",
            f"Posting sizes:      {qr.posting_sizes!r}",
            f"Candidates:         {qr.candidate_count} / {qr.total_files} files ({sel_pct})",
            f"Selectivity:        {verdict} (threshold: {threshold_pct})",
            f"Mode:               {qr.mode}",
        ]
        return "\n".join(lines)

    def test_format_threshold_exceeded(self, tmp_path: Path) -> None:
        files = {f"f{i:04d}.py": f"def common_func_{i}(): pass\n" for i in range(150)}
        proj = _create_project(tmp_path, files)
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        qr = idx.query("def common", explain=True, selectivity_threshold=0.10)
        output = self._format(qr, "def common")
        assert "SKIP (threshold exceeded)" in output
        assert "full-scan-threshold" in output
        idx.close()

    def test_format_posting_sizes_present(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"a.py": "def unique_thing(): pass\n"})
        idx = TrigramIndex(index_dir=str(proj / ".attocode" / "index"))
        idx.build(str(proj))
        qr = idx.query("unique_thing", explain=True)
        output = self._format(qr, "unique_thing")
        assert "Posting sizes:" in output
        # Should have actual numbers, not empty list
        assert "[]" not in output.split("Posting sizes:")[1].split("\n")[0]
        idx.close()
