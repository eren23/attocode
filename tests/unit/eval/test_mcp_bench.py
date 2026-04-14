"""Tests for code-intel-bench modules."""
from __future__ import annotations

import pytest

from eval.mcp_bench.schema import BenchSuiteResult, TaskResult, BenchConfig
from eval.mcp_bench.scoring import (
    score_deterministic,
    _score_security,
    _score_generic,
    match_ground_truth,
    score_task,
)
from eval.mcp_bench.schema import BenchTask
from eval.llm_fp_filter.filter import (
    _parse_response,
    classify_finding,
    FPVerdict,
    FPClassification,
)
from eval.llm_fp_filter.benchmark import FilterBenchmarkResult


# ---------------------------------------------------------------------------
# TestBenchSuiteResult
# ---------------------------------------------------------------------------


class TestBenchSuiteResult:
    """Test aggregate computation on BenchSuiteResult."""

    def test_empty_task_results(self):
        suite = BenchSuiteResult()
        suite.compute_aggregates()
        assert suite.total_tasks == 0
        assert suite.mean_score == 0.0
        assert suite.median_score == 0.0
        assert suite.per_category == {}

    def test_aggregates_with_results(self):
        suite = BenchSuiteResult(
            task_results=[
                TaskResult(task_id="t1", category="orientation", score=2.0),
                TaskResult(task_id="t2", category="orientation", score=4.0),
                TaskResult(task_id="t3", category="security_scanning", score=5.0),
            ]
        )
        suite.compute_aggregates()
        assert suite.total_tasks == 3
        assert suite.completed_tasks == 3
        assert suite.errored_tasks == 0
        assert suite.mean_score == pytest.approx(11.0 / 3, rel=1e-2)
        assert suite.median_score == pytest.approx(4.0)

    def test_per_category_breakdown(self):
        suite = BenchSuiteResult(
            task_results=[
                TaskResult(task_id="t1", category="orientation", score=3.0),
                TaskResult(task_id="t2", category="orientation", score=5.0),
                TaskResult(task_id="t3", category="security_scanning", score=4.0),
            ]
        )
        suite.compute_aggregates()
        assert "orientation" in suite.per_category
        assert "security_scanning" in suite.per_category
        assert suite.per_category["orientation"]["mean_score"] == pytest.approx(4.0)
        assert suite.per_category["orientation"]["count"] == 2
        assert suite.per_category["security_scanning"]["mean_score"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# TestScoring
# ---------------------------------------------------------------------------


class TestScoring:
    """Test deterministic and ground-truth scoring functions."""

    def test_score_deterministic_orientation(self):
        task = BenchTask(
            task_id="orient-1",
            category="orientation",
            repo="test-repo",
            query="Explore the codebase",
        )
        # Output that contains orientation keywords
        output = (
            "Languages: Python, TypeScript\n"
            "Entry Points: src/main.py, src/cli.py\n"
            "Dependencies: requests, fastapi\n"
            "The project has a modular structure with clear separation."
        )
        score = score_deterministic(task, output)
        assert score > 0

    def test_score_security_with_cwe(self):
        task = BenchTask(
            task_id="sec-1",
            category="security_scanning",
            repo="test-repo",
            query="Scan for SQL injection",
            ground_truth={
                "expected_cwes": ["CWE-89"],
                "min_findings": 1,
            },
        )
        output = (
            "Finding: SQL injection vulnerability\n"
            "CWE-89 detected in db/queries.py:42\n"
            "Severity: high\n"
        )
        score = _score_security(task, output)
        assert score > 0

    def test_score_generic_empty(self):
        assert _score_generic("") == 0.0

    def test_score_generic_long_with_refs(self):
        # Long output with file:line references → should score > 1
        output = (
            "Analysis of the module structure.\n"
            "Found references in utils.py:10, handler.py:55.\n"
            "The function `process_data` imports from core module.\n"
            + "x" * 500
        )
        score = _score_generic(output)
        assert score > 1

    def test_match_ground_truth_must_contain_present(self):
        task = BenchTask(
            task_id="gt-1",
            category="orientation",
            repo="test-repo",
            query="test",
            ground_truth={"must_contain": ["fastapi", "router"]},
        )
        output = "The project uses FastAPI with a router pattern."
        result = match_ground_truth(task, output)
        assert result["contains:fastapi"]["matched"] is True
        assert result["contains:router"]["matched"] is True

    def test_match_ground_truth_must_contain_absent(self):
        task = BenchTask(
            task_id="gt-2",
            category="orientation",
            repo="test-repo",
            query="test",
            ground_truth={"must_contain": ["django"]},
        )
        output = "The project uses FastAPI."
        result = match_ground_truth(task, output)
        assert result["contains:django"]["matched"] is False

    def test_match_ground_truth_must_mention_files(self):
        task = BenchTask(
            task_id="gt-3",
            category="orientation",
            repo="test-repo",
            query="test",
            ground_truth={"must_mention_files": ["src/main.py"]},
        )
        output = "The entry point is main.py in the src directory."
        result = match_ground_truth(task, output)
        # Matches on filename "main.py"
        assert result["file:src/main.py"]["matched"] is True

    def test_match_ground_truth_expected_cwes(self):
        task = BenchTask(
            task_id="gt-4",
            category="security_scanning",
            repo="test-repo",
            query="test",
            ground_truth={"expected_cwes": ["CWE-89", "CWE-78"]},
        )
        output = "Found CWE-89 SQL injection. No command injection."
        result = match_ground_truth(task, output)
        assert result["cwe:CWE-89"]["matched"] is True
        assert result["cwe:CWE-78"]["matched"] is False

    def test_score_task_blending(self):
        task = BenchTask(
            task_id="blend-1",
            category="security_scanning",
            repo="test-repo",
            query="Find vulnerabilities",
            ground_truth={"must_contain": ["vulnerability"]},
        )
        output = "Found a vulnerability in the auth module."
        result = score_task(task, output)
        # Deterministic score (security scorer) and ground truth both contribute.
        # 70% deterministic + 30% ground truth.
        assert result.task_id == "blend-1"
        assert result.score >= 0
        assert result.deterministic_score >= 0
        assert result.ground_truth_match is not None
        # Since ground truth matches (1/1 = 100%), GT contribution is 0.3 * 5.0 = 1.5
        gt_matches = result.ground_truth_match
        matched_count = sum(1 for v in gt_matches.values() if v.get("matched"))
        assert matched_count == 1


# ---------------------------------------------------------------------------
# TestLLMFPFilter
# ---------------------------------------------------------------------------


class TestLLMFPFilter:
    """Test the LLM-based FP filter response parsing and classify_finding."""

    def test_parse_true_positive(self):
        text = "VERDICT: TRUE_POSITIVE\nCONFIDENCE: 0.9\nREASONING: real issue"
        result = _parse_response("rule-1", "file.py", 10, text, 100, 50.0)
        assert result.verdict == FPVerdict.TRUE_POSITIVE
        assert result.confidence == pytest.approx(0.9)
        assert result.reasoning == "real issue"

    def test_parse_false_positive(self):
        text = "VERDICT: FALSE_POSITIVE\nCONFIDENCE: 0.8\nREASONING: test code"
        result = _parse_response("rule-2", "test.py", 5, text, 80, 30.0)
        assert result.verdict == FPVerdict.FALSE_POSITIVE
        assert result.confidence == pytest.approx(0.8)

    def test_parse_empty_string(self):
        result = _parse_response("rule-3", "file.py", 1, "", 0, 0.0)
        assert result.verdict == FPVerdict.UNCERTAIN

    def test_parse_malformed_no_verdict(self):
        text = "This is just some random text without proper format."
        result = _parse_response("rule-4", "file.py", 1, text, 50, 10.0)
        assert result.verdict == FPVerdict.UNCERTAIN

    def test_classify_finding_no_api_key(self, monkeypatch):
        # Ensure no ANTHROPIC_API_KEY in env
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = classify_finding(
            rule_id="rule-5",
            severity="high",
            description="test desc",
            cwe="CWE-89",
            file="app.py",
            line=42,
            matched_line="cursor.execute(query)",
            code_context="def handler():\n    cursor.execute(query)",
            api_key="",
        )
        assert result.verdict == FPVerdict.UNCERTAIN
        assert "No API key" in result.reasoning

    def test_filter_benchmark_result_metrics(self):
        r = FilterBenchmarkResult(
            total_findings=14,
            classified=14,
            correct=11,
            incorrect=3,
            filter_tp=8,
            filter_fp=2,
            filter_tn=3,
            filter_fn=1,
        )
        # accuracy = 11/14
        assert r.accuracy == pytest.approx(11 / 14, rel=1e-3)
        # filter_precision = 8/(8+2) = 0.8
        assert r.filter_precision == pytest.approx(0.8)
        # filter_recall = 8/(8+1) = 0.888...
        assert r.filter_recall == pytest.approx(8 / 9, rel=1e-3)
