"""Tests for TemporalCouplingAnalyzer — co-change, churn, and merge risk."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from attocode.integrations.context.temporal_coupling import (
    TemporalCouplingAnalyzer,
)


# Simulated git log output (--numstat --format=%H|%an|%aI)
_SAMPLE_GIT_LOG = """\
abc1234|Alice|2026-03-01
5\t2\tsrc/auth.py
3\t1\tsrc/models.py
2\t0\tsrc/utils.py

def5678|Bob|2026-03-05
10\t5\tsrc/auth.py
4\t2\tsrc/models.py

ghi9012|Alice|2026-03-10
1\t1\tsrc/utils.py
8\t3\tsrc/api.py

jkl3456|Bob|2026-03-12
6\t2\tsrc/auth.py
2\t1\tsrc/models.py
1\t0\tsrc/api.py

mno7890|Alice|2026-03-15
3\t1\tsrc/auth.py

pqr1234|Bob|2026-03-18
2\t1\tsrc/api.py
1\t0\tsrc/utils.py
"""


@pytest.fixture()
def analyzer(tmp_path):
    """Analyzer with mocked git output."""
    a = TemporalCouplingAnalyzer(project_dir=str(tmp_path))
    with patch.object(a, "_run_git", return_value=_SAMPLE_GIT_LOG):
        a._ensure_cache(90)
    return a


class TestCacheBuilding:
    def test_commit_count(self, analyzer):
        assert len(analyzer._commit_files) == 6

    def test_file_commit_counts(self, analyzer):
        assert analyzer._file_commits["src/auth.py"] == 4
        assert analyzer._file_commits["src/models.py"] == 3
        assert analyzer._file_commits["src/utils.py"] == 3
        assert analyzer._file_commits["src/api.py"] == 3

    def test_co_change_matrix_populated(self, analyzer):
        # auth.py and models.py co-change in commits abc1234, def5678, jkl3456
        key = ("src/auth.py", "src/models.py")
        assert analyzer._co_change_matrix.get(key, 0) == 3

    def test_file_churn_data(self, analyzer):
        churn = analyzer._file_churn["src/auth.py"]
        assert churn["commits"] == 4
        assert "Alice" in churn["authors"]
        assert "Bob" in churn["authors"]
        assert churn["added"] == 24  # 5+10+6+3
        assert churn["removed"] == 10  # 2+5+2+1


class TestChangeCoupling:
    def test_coupling_for_auth(self, analyzer):
        results = analyzer.get_change_coupling("src/auth.py", days=90, min_coupling=0.0)
        assert len(results) > 0
        # auth.py (4 commits) co-changes with models.py (3 commits) 3 times
        # coupling = 3 / min(4, 3) = 1.0
        models_entry = next(e for e in results if e.path == "src/models.py")
        assert models_entry.coupling_score == 1.0
        assert models_entry.co_changes == 3

    def test_coupling_min_filter(self, analyzer):
        results = analyzer.get_change_coupling("src/auth.py", days=90, min_coupling=0.9)
        paths = [e.path for e in results]
        assert "src/models.py" in paths
        # utils.py co-changes only once with auth.py, should be filtered
        assert "src/utils.py" not in paths

    def test_coupling_for_unknown_file(self, analyzer):
        results = analyzer.get_change_coupling("nonexistent.py", days=90)
        assert results == []

    def test_coupling_top_k(self, analyzer):
        results = analyzer.get_change_coupling("src/auth.py", days=90, min_coupling=0.0, top_k=1)
        assert len(results) == 1


class TestChurnHotspots:
    def test_hotspots_returns_results(self, analyzer):
        results = analyzer.get_churn_hotspots(days=90)
        assert len(results) > 0

    def test_hotspots_ordered_by_score(self, analyzer):
        results = analyzer.get_churn_hotspots(days=90)
        scores = [e.churn_score for e in results]
        assert scores == sorted(scores, reverse=True)

    def test_auth_is_top_hotspot(self, analyzer):
        results = analyzer.get_churn_hotspots(days=90)
        # auth.py has most commits (4) and most churn
        assert results[0].path == "src/auth.py"

    def test_churn_score_range(self, analyzer):
        results = analyzer.get_churn_hotspots(days=90)
        for entry in results:
            assert 0.0 <= entry.churn_score <= 1.0

    def test_top_n_limit(self, analyzer):
        results = analyzer.get_churn_hotspots(days=90, top_n=2)
        assert len(results) == 2


class TestChurnScore:
    def test_known_file(self, analyzer):
        score = analyzer.get_churn_score("src/auth.py", days=90)
        assert score > 0.0
        assert score <= 1.0

    def test_unknown_file(self, analyzer):
        score = analyzer.get_churn_score("nonexistent.py", days=90)
        assert score == 0.0


class TestMergeRisk:
    def test_temporal_predictions(self, analyzer):
        results = analyzer.get_merge_risk(
            ["src/auth.py"], days=90, min_confidence=0.0,
        )
        # models.py strongly coupled with auth.py, should appear
        paths = [e.path for e in results]
        assert "src/models.py" in paths

    def test_structural_predictions(self, analyzer):
        results = analyzer.get_merge_risk(
            ["src/auth.py"],
            days=90,
            dep_graph_forward={"src/auth.py": {"src/utils.py"}},
            dep_graph_reverse={},
            min_confidence=0.0,
        )
        paths = [e.path for e in results]
        assert "src/utils.py" in paths

    def test_both_reason_when_temporal_and_structural(self, analyzer):
        results = analyzer.get_merge_risk(
            ["src/auth.py"],
            days=90,
            dep_graph_forward={"src/auth.py": {"src/models.py"}},
            dep_graph_reverse={},
            min_confidence=0.0,
        )
        models_entry = next(e for e in results if e.path == "src/models.py")
        assert models_entry.reason == "both"

    def test_excludes_input_files(self, analyzer):
        results = analyzer.get_merge_risk(
            ["src/auth.py"], days=90, min_confidence=0.0,
        )
        paths = [e.path for e in results]
        assert "src/auth.py" not in paths

    def test_confidence_filter(self, analyzer):
        results = analyzer.get_merge_risk(
            ["src/auth.py"], days=90, min_confidence=0.99,
        )
        # Very high threshold should filter most results
        assert len(results) == 0 or all(e.confidence >= 0.99 for e in results)


class TestEmptyHistory:
    def test_empty_git_log(self, tmp_path):
        analyzer = TemporalCouplingAnalyzer(project_dir=str(tmp_path))
        with patch.object(analyzer, "_run_git", return_value=""):
            assert analyzer.get_change_coupling("any.py", days=90) == []
            assert analyzer.get_churn_hotspots(days=90) == []
            assert analyzer.get_merge_risk(["any.py"], days=90) == []
