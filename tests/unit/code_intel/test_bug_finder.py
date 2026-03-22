"""Tests for bug finder."""

from __future__ import annotations

import pytest

from attocode.code_intel.bug_finder import (
    BugReport,
    Finding,
    FindingCategory,
    Severity,
    parse_diff_files,
    scan_diff,
    scan_text,
)


class TestScanText:
    def test_bare_except(self) -> None:
        code = "try:\n    x = 1\nexcept:\n    pass"
        findings = scan_text(code, "test.py")
        assert any(f.category == FindingCategory.ERROR_HANDLING for f in findings)

    def test_eval_detected(self) -> None:
        findings = scan_text("result = eval(user_input)", "test.py")
        assert any(f.category == FindingCategory.SECURITY for f in findings)

    def test_exec_detected(self) -> None:
        findings = scan_text("exec(code_string)", "test.py")
        assert any(f.category == FindingCategory.SECURITY for f in findings)

    def test_shell_injection(self) -> None:
        findings = scan_text("subprocess.call(cmd, shell=True)", "test.py")
        security = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(security) >= 1

    def test_todo_detected(self) -> None:
        findings = scan_text("# TODO: fix this later", "test.py")
        assert any("TODO" in f.description for f in findings)

    def test_clean_code(self) -> None:
        code = "def add(a: int, b: int) -> int:\n    return a + b"
        findings = scan_text(code, "test.py")
        # Should have no high-severity findings
        high = [f for f in findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]
        assert len(high) == 0

    def test_line_numbers(self) -> None:
        code = "x = 1\ny = 2\nresult = eval(z)"
        findings = scan_text(code, "test.py")
        eval_finding = next(f for f in findings if f.category == FindingCategory.SECURITY)
        assert eval_finding.line == 3

    def test_code_snippet_captured(self) -> None:
        findings = scan_text("dangerous = eval(input())", "test.py")
        assert findings[0].code_snippet


class TestParseDiffFiles:
    def test_single_file(self) -> None:
        diff = (
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " existing\n"
            "+new_line\n"
            " more\n"
        )
        files = parse_diff_files(diff)
        assert len(files) == 1
        assert files[0][0] == "foo.py"
        assert "new_line" in files[0][1]

    def test_multiple_files(self) -> None:
        diff = (
            "--- a/a.py\n+++ b/a.py\n+line_a\n"
            "--- a/b.py\n+++ b/b.py\n+line_b\n"
        )
        files = parse_diff_files(diff)
        assert len(files) == 2

    def test_empty_diff(self) -> None:
        assert parse_diff_files("") == []


class TestScanDiff:
    def test_scan_diff_finds_issues(self) -> None:
        diff = (
            "--- a/bad.py\n"
            "+++ b/bad.py\n"
            "+result = eval(user_input)\n"
            "+try:\n"
            "+    x = 1\n"
            "+except:\n"
            "+    pass\n"
        )
        report = scan_diff(diff)
        assert report.files_scanned == 1
        assert len(report.findings) >= 2

    def test_scan_diff_skips_non_code(self) -> None:
        diff = (
            "--- a/readme.md\n"
            "+++ b/readme.md\n"
            "+eval(something)\n"
        )
        report = scan_diff(diff)
        assert len(report.findings) == 0  # .md files skipped


class TestBugReport:
    def test_critical_count(self) -> None:
        report = BugReport(findings=[
            Finding(file="a.py", line=1, severity=Severity.CRITICAL,
                    category=FindingCategory.SECURITY, confidence=0.9,
                    description="Critical issue"),
            Finding(file="b.py", line=2, severity=Severity.LOW,
                    category=FindingCategory.LOGIC_ERROR, confidence=0.5,
                    description="Minor issue"),
        ])
        assert report.critical_count == 1
        assert report.high_count == 0

    def test_filter_by_confidence(self) -> None:
        report = BugReport(findings=[
            Finding(file="a.py", line=1, severity=Severity.HIGH,
                    category=FindingCategory.SECURITY, confidence=0.9,
                    description="High confidence"),
            Finding(file="b.py", line=2, severity=Severity.HIGH,
                    category=FindingCategory.SECURITY, confidence=0.3,
                    description="Low confidence"),
        ])
        filtered = report.filter_by_confidence(0.5)
        assert len(filtered) == 1
        assert filtered[0].description == "High confidence"

    def test_format_report(self) -> None:
        report = BugReport(
            findings=[
                Finding(file="a.py", line=10, severity=Severity.HIGH,
                        category=FindingCategory.SECURITY, confidence=0.9,
                        description="Eval usage", suggestion="Use ast.literal_eval"),
            ],
            files_scanned=5,
            lines_analyzed=100,
        )
        text = report.format_report()
        assert "a.py:10" in text
        assert "Eval usage" in text
        assert "ast.literal_eval" in text

    def test_format_report_empty(self) -> None:
        report = BugReport(files_scanned=3)
        text = report.format_report()
        assert "No findings" in text
