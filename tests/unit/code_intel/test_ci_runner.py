"""Tests for CI runner, config loading, and output formatting."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.rules.ci import (
    CIConfig,
    CIRunner,
    format_ci_summary,
    format_github_annotations,
    load_ci_config,
)
from attocode.code_intel.rules.model import (
    EnrichedFinding,
    RuleCategory,
    RuleSeverity,
)


def _make_finding(**overrides) -> EnrichedFinding:
    defaults = dict(
        rule_id="test/rule",
        rule_name="Test",
        severity=RuleSeverity.HIGH,
        category=RuleCategory.SECURITY,
        confidence=0.9,
        file="src/app.py",
        line=10,
        code_snippet="bad()",
        description="Bad call detected",
    )
    defaults.update(overrides)
    return EnrichedFinding(**defaults)


class TestLoadCIConfig:
    def test_default_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = load_ci_config(tmpdir)
            assert cfg.fail_on == RuleSeverity.HIGH
            assert cfg.baseline == ""
            assert cfg.exclude_rules == []

    def test_loads_from_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ci_dir = Path(tmpdir) / ".attocode"
            ci_dir.mkdir()
            (ci_dir / "ci.yaml").write_text(
                "fail_on: medium\nbaseline: main\nexclude_rules:\n  - rule-a\n"
            )
            cfg = load_ci_config(tmpdir)
            assert cfg.fail_on == RuleSeverity.MEDIUM
            assert cfg.baseline == "main"
            assert cfg.exclude_rules == ["rule-a"]

    def test_invalid_severity_uses_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ci_dir = Path(tmpdir) / ".attocode"
            ci_dir.mkdir()
            (ci_dir / "ci.yaml").write_text("fail_on: invalid_severity\n")
            cfg = load_ci_config(tmpdir)
            assert cfg.fail_on == RuleSeverity.HIGH  # default

    def test_corrupt_yaml_returns_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ci_dir = Path(tmpdir) / ".attocode"
            ci_dir.mkdir()
            (ci_dir / "ci.yaml").write_text("[invalid yaml: {")
            cfg = load_ci_config(tmpdir)
            assert cfg.fail_on == RuleSeverity.HIGH


class TestFormatGithubAnnotations:
    def test_empty_findings(self):
        assert format_github_annotations([]) == ""

    def test_high_severity_is_error(self):
        result = format_github_annotations([_make_finding(severity=RuleSeverity.HIGH)])
        assert result.startswith("::error")

    def test_medium_severity_is_warning(self):
        result = format_github_annotations([_make_finding(severity=RuleSeverity.MEDIUM)])
        assert result.startswith("::warning")

    def test_low_severity_is_notice(self):
        result = format_github_annotations([_make_finding(severity=RuleSeverity.LOW)])
        assert result.startswith("::notice")

    def test_file_and_line_in_output(self):
        result = format_github_annotations([_make_finding(file="src/x.py", line=42)])
        assert "file=src/x.py" in result
        assert "line=42" in result

    def test_newline_in_description_encoded(self):
        result = format_github_annotations([_make_finding(
            description="line1\nline2",
        )])
        assert "%0A" in result

    def test_percent_in_description_encoded(self):
        result = format_github_annotations([_make_finding(
            description="100% bad",
        )])
        assert "%25" in result


class TestFormatCISummary:
    def test_pass_status(self):
        from attocode.code_intel.rules.ci import CIResult
        result = CIResult(findings=[], exit_code=0, files_scanned=5, rules_applied=10)
        summary = format_ci_summary(result)
        assert "PASS" in summary

    def test_fail_status(self):
        from attocode.code_intel.rules.ci import CIResult
        result = CIResult(
            findings=[_make_finding()],
            exit_code=1,
            files_scanned=5,
            rules_applied=10,
            findings_above_threshold=1,
        )
        summary = format_ci_summary(result)
        assert "FAIL" in summary
        assert "1 above threshold" in summary


class TestCIRunner:
    def test_scan_with_findings(self):
        """Scan a file with known-bad patterns and verify findings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a file containing a pattern that builtin rules detect
            src = Path(tmpdir) / "vuln.py"
            src.write_text("result = __import__('subprocess').call(cmd, shell=True)\n")

            config = CIConfig(fail_on=RuleSeverity.MEDIUM, min_confidence=0.3)
            runner = CIRunner(tmpdir, config=config)
            result = runner.run()

            assert result.findings
            assert result.exit_code == 1
            assert result.files_scanned == 1

    def test_scan_clean_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "clean.py"
            src.write_text("def add(a, b):\n    return a + b\n")

            config = CIConfig(fail_on=RuleSeverity.HIGH, min_confidence=0.5)
            runner = CIRunner(tmpdir, config=config)
            result = runner.run()

            assert result.exit_code == 0

    def test_exclude_rules(self):
        """Verify excluded rules produce no findings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "vuln.py"
            src.write_text("result = __import__('subprocess').call(cmd, shell=True)\n")

            # First run — collect findings
            config1 = CIConfig(fail_on=RuleSeverity.HIGH, min_confidence=0.3)
            runner1 = CIRunner(tmpdir, config=config1)
            result1 = runner1.run()
            rule_ids = list({f.rule_id for f in result1.findings})

            # Second run — exclude all found rules
            config2 = CIConfig(
                fail_on=RuleSeverity.HIGH,
                min_confidence=0.3,
                exclude_rules=rule_ids,
            )
            runner2 = CIRunner(tmpdir, config=config2)
            result2 = runner2.run()
            assert len(result2.findings) == 0

    def test_sarif_output_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "vuln.py"
            src.write_text("result = __import__('subprocess').call(cmd, shell=True)\n")

            sarif_path = str(Path(tmpdir) / "results.sarif")
            config = CIConfig(
                fail_on=RuleSeverity.HIGH,
                min_confidence=0.3,
                sarif_output=sarif_path,
            )
            runner = CIRunner(tmpdir, config=config)
            runner.run()

            import json
            sarif = json.loads(Path(sarif_path).read_text())
            assert sarif["version"] == "2.1.0"
            assert len(sarif["runs"][0]["results"]) > 0
