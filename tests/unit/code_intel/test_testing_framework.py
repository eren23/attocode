"""Tests for the rule testing framework itself."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    UnifiedRule,
)
from attocode.code_intel.rules.testing import (
    Expectation,
    RuleTestRunner,
    _finding_matches_rule,
    format_test_report,
    parse_annotations,
    validate_inline_test_cases,
)


class TestParseAnnotations:
    def test_expect_annotation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1  # expect: rule-a\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert len(anns) == 1
        assert anns[0].kind == "expect"
        assert anns[0].rule_id == "rule-a"
        assert anns[0].line == 1

    def test_ok_annotation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("safe_call()  # ok: rule-b\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert len(anns) == 1
        assert anns[0].kind == "ok"

    def test_todoruleid_annotation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("edge_case()  # todoruleid: rule-c\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert len(anns) == 1
        assert anns[0].kind == "todoruleid"

    def test_double_slash_comments(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write("Sprintf()  // expect: go-rule\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert len(anns) == 1
        assert anns[0].rule_id == "go-rule"

    def test_multiple_annotation_types(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("bad()  # expect: rule-1\n")
            f.write("safe()  # ok: rule-2\n")
            f.write("maybe()  # todoruleid: rule-3\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert len(anns) == 3
        kinds = {a.kind for a in anns}
        assert kinds == {"expect", "ok", "todoruleid"}

    def test_nonexistent_file_returns_empty(self):
        anns = parse_annotations("/nonexistent/path/file.py")
        assert anns == []

    def test_no_annotations(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1\ny = 2\n")
            f.flush()
            anns = parse_annotations(f.name)
        assert anns == []


class TestFindingMatchesRule:
    def test_exact_match(self):
        assert _finding_matches_rule("security/sql-injection", "security/sql-injection")

    def test_suffix_match(self):
        assert _finding_matches_rule("plugin:team/sql-injection", "sql-injection")

    def test_no_match(self):
        assert not _finding_matches_rule("security/sql-injection", "xss")

    def test_no_substring_match(self):
        """Substring matching was removed to prevent overly broad suppression."""
        assert not _finding_matches_rule("no-raw-sql-usage", "sql")


class TestValidateInlineTestCases:
    def _make_rule(self, pattern_str: str = r"dangerous\(") -> UnifiedRule:
        return UnifiedRule(
            id="test",
            name="test",
            description="test",
            severity=RuleSeverity.HIGH,
            category=RuleCategory.SECURITY,
            pattern=re.compile(pattern_str),
        )

    def test_matching_case_passes(self):
        rule = self._make_rule()
        errors = validate_inline_test_cases(rule, [
            {"code": "dangerous(x)", "should_match": True},
        ])
        assert errors == []

    def test_non_matching_case_passes(self):
        rule = self._make_rule()
        errors = validate_inline_test_cases(rule, [
            {"code": "safe(x)", "should_match": False},
        ])
        assert errors == []

    def test_expected_match_but_no_match(self):
        rule = self._make_rule()
        errors = validate_inline_test_cases(rule, [
            {"code": "safe(x)", "should_match": True},
        ])
        assert len(errors) == 1
        assert "expected match" in errors[0]

    def test_expected_no_match_but_matches(self):
        rule = self._make_rule()
        errors = validate_inline_test_cases(rule, [
            {"code": "dangerous(x)", "should_match": False},
        ])
        assert len(errors) == 1
        assert "expected no match" in errors[0]

    def test_no_pattern_returns_empty(self):
        rule = UnifiedRule(
            id="test", name="test", description="test",
            severity=RuleSeverity.HIGH,
            category=RuleCategory.SECURITY,
            pattern=None,
        )
        errors = validate_inline_test_cases(rule, [
            {"code": "anything", "should_match": True},
        ])
        assert errors == []


class TestRuleTestRunner:
    def _make_rule(self, rule_id: str = "test-rule", pattern_str: str = r"bad_func\(") -> UnifiedRule:
        return UnifiedRule(
            id=rule_id,
            name=rule_id,
            description="test rule",
            severity=RuleSeverity.HIGH,
            category=RuleCategory.SECURITY,
            pattern=re.compile(pattern_str),
        )

    def test_expect_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("bad_func(x)  # expect: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert result.ok
            assert len(result.passed) == 1

    def test_expect_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("safe_func(x)  # expect: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert not result.ok
            assert len(result.failed) == 1

    def test_ok_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("safe_func(x)  # ok: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert result.ok
            assert len(result.passed) == 1

    def test_ok_detects_false_positive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("bad_func(x)  # ok: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert not result.ok
            assert len(result.false_positives) == 1

    def test_todoruleid_not_matching_is_not_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("safe_func(x)  # todoruleid: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert result.ok  # todoruleid not matching is expected

    def test_todoruleid_unexpected_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("bad_func(x)  # todoruleid: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            result = runner.run_test_file(str(f))
            assert result.ok  # unexpected passes don't fail
            assert len(result.todoruleid_unexpected_passes) == 1

    def test_run_test_suite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("bad_func(x)  # expect: test-rule\nsafe(y)\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            suite = runner.run_test_suite(tmpdir)
            assert len(suite.file_results) == 1
            assert suite.ok

    def test_format_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text("safe(x)  # expect: test-rule\n")

            runner = RuleTestRunner([self._make_rule()], project_dir=tmpdir)
            suite = runner.run_test_suite(tmpdir)
            report = format_test_report(suite)
            assert "FAIL" in report
            assert "Missing Expected" in report
