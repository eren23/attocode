"""Tests for security scanner autofix diff generation.

When a scanned file triggers a pattern that has a corresponding entry in
``_AUTOFIX_TEMPLATES``, the scanner should populate ``SecurityFinding.fix_diff``
with a unified-diff snippet showing the mechanical fix.  Patterns without a
template must leave ``fix_diff`` empty.  ``format_report()`` must render the
diff under an "Autofix:" heading when present, and omit it otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.security.scanner import (
    SecurityFinding,
    SecurityScanner,
    _AUTOFIX_TEMPLATES,
)
from attocode.integrations.security.patterns import Category, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VULNERABLE_SNIPPETS: dict[str, tuple[str, str, str]] = {
    # pattern_name -> (filename, vulnerable_code, expected_replacement_fragment)
    "python_yaml_unsafe": (
        "loader.py",
        "data = yaml.load(open('cfg.yml'))\n",
        "yaml.safe_load(",
    ),
    "python_shell_true": (
        "runner.py",
        "subprocess.run(cmd, shell=True)\n",
        "shell=False",
    ),
    "python_tempfile_insecure": (
        "tmp.py",
        "path = tempfile.mktemp()\n",
        "tempfile.mkstemp(",
    ),
    "python_verify_false": (
        "client.py",
        "resp = requests.get(url, verify=False)\n",
        "verify=True",
    ),
}

# A pattern that exists in ANTI_PATTERNS but has NO autofix template.
# Note: these strings are test fixtures for the security scanner detector,
# NOT actual code execution — they are written to temp files and scanned.
_NO_TEMPLATE_SNIPPET = (
    "danger.py",
    "result = eval(user_input)\n",  # noqa: S307 — triggers python_dynamic_eval
)


# ---------------------------------------------------------------------------
# TestAutofixTemplates
# ---------------------------------------------------------------------------


class TestAutofixTemplates:
    """Tests for _AUTOFIX_TEMPLATES definitions."""

    def test_templates_dict_is_non_empty(self) -> None:
        assert len(_AUTOFIX_TEMPLATES) > 0

    @pytest.mark.parametrize("name", list(_AUTOFIX_TEMPLATES))
    def test_template_values_are_search_replace_tuples(self, name: str) -> None:
        entry = _AUTOFIX_TEMPLATES[name]
        assert isinstance(entry, tuple)
        assert len(entry) == 2
        search, replace = entry
        assert isinstance(search, str) and len(search) > 0
        assert isinstance(replace, str) and len(replace) > 0

    @pytest.mark.parametrize("name", list(_AUTOFIX_TEMPLATES))
    def test_search_and_replace_differ(self, name: str) -> None:
        search, replace = _AUTOFIX_TEMPLATES[name]
        assert search != replace

    def test_expected_templates_present(self) -> None:
        expected = {
            "python_yaml_unsafe",
            "python_shell_true",
            "python_tempfile_insecure",
            "python_verify_false",
        }
        assert expected.issubset(_AUTOFIX_TEMPLATES.keys())


# ---------------------------------------------------------------------------
# TestSecurityFindingDefaults
# ---------------------------------------------------------------------------


class TestSecurityFindingDefaults:
    """Tests that SecurityFinding.fix_diff exists and defaults correctly."""

    def test_fix_diff_defaults_to_empty_string(self) -> None:
        finding = SecurityFinding(
            severity=Severity.HIGH,
            category=Category.ANTI_PATTERN,
            file_path="x.py",
            line=1,
            message="msg",
            recommendation="rec",
        )
        assert finding.fix_diff == ""

    def test_fix_diff_can_be_set(self) -> None:
        finding = SecurityFinding(
            severity=Severity.HIGH,
            category=Category.ANTI_PATTERN,
            file_path="x.py",
            line=1,
            message="msg",
            recommendation="rec",
            fix_diff="--- a/x.py\n+++ b/x.py\n",
        )
        assert finding.fix_diff.startswith("---")


# ---------------------------------------------------------------------------
# TestFixDiffGeneration
# ---------------------------------------------------------------------------


class TestFixDiffGeneration:
    """Tests for fix_diff population in _scan_content via scan()."""

    @pytest.mark.parametrize(
        "pattern_name",
        list(_VULNERABLE_SNIPPETS),
    )
    def test_fix_diff_populated_for_template_pattern(
        self, tmp_path: Path, pattern_name: str,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS[pattern_name]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == pattern_name
        ]
        assert len(matching) >= 1, (
            f"Expected at least one finding for {pattern_name}"
        )
        finding = matching[0]
        assert finding.fix_diff != "", (
            f"fix_diff should be populated for {pattern_name}"
        )

    @pytest.mark.parametrize(
        "pattern_name",
        list(_VULNERABLE_SNIPPETS),
    )
    def test_fix_diff_is_unified_diff_format(
        self, tmp_path: Path, pattern_name: str,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS[pattern_name]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == pattern_name
        ]
        finding = matching[0]
        lines = finding.fix_diff.splitlines()
        assert lines[0].startswith("--- a/")
        assert lines[1].startswith("+++ b/")
        assert lines[2].startswith("@@")

    @pytest.mark.parametrize(
        "pattern_name",
        list(_VULNERABLE_SNIPPETS),
    )
    def test_fix_diff_contains_corrected_replacement(
        self, tmp_path: Path, pattern_name: str,
    ) -> None:
        filename, code, replacement_fragment = _VULNERABLE_SNIPPETS[pattern_name]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == pattern_name
        ]
        finding = matching[0]
        # The '+' line in the diff must contain the replacement text
        plus_lines = [
            l for l in finding.fix_diff.splitlines()
            if l.startswith("+") and not l.startswith("+++")
        ]
        assert any(replacement_fragment in l for l in plus_lines), (
            f"Expected '{replacement_fragment}' in a '+' line of the diff"
        )

    @pytest.mark.parametrize(
        "pattern_name",
        list(_VULNERABLE_SNIPPETS),
    )
    def test_fix_diff_contains_original_line_as_removal(
        self, tmp_path: Path, pattern_name: str,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS[pattern_name]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == pattern_name
        ]
        finding = matching[0]
        minus_lines = [
            l for l in finding.fix_diff.splitlines()
            if l.startswith("-") and not l.startswith("---")
        ]
        assert len(minus_lines) == 1, "Expected exactly one removal line"
        # The removal line should contain the original search string
        search_str = _AUTOFIX_TEMPLATES[pattern_name][0]
        assert search_str in minus_lines[0]

    def test_no_fix_diff_for_pattern_without_template(
        self, tmp_path: Path,
    ) -> None:
        filename, code = _NO_TEMPLATE_SNIPPET
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        eval_findings = [
            f for f in report.findings if f.pattern_name == "python_dynamic_eval"
        ]
        assert len(eval_findings) >= 1, (
            "Expected at least one finding for python_dynamic_eval"
        )
        for finding in eval_findings:
            assert finding.fix_diff == "", (
                "fix_diff must be empty for patterns without an autofix template"
            )

    def test_fix_diff_file_paths_match_finding(
        self, tmp_path: Path,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS["python_yaml_unsafe"]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == "python_yaml_unsafe"
        ]
        finding = matching[0]
        diff_lines = finding.fix_diff.splitlines()
        # --- a/<path> and +++ b/<path> should reference the finding's file_path
        assert finding.file_path in diff_lines[0]
        assert finding.file_path in diff_lines[1]

    def test_fix_diff_hunk_header_contains_correct_line_number(
        self, tmp_path: Path,
    ) -> None:
        # Put the vulnerable line on line 3 by adding two blank lines before it
        code = "\n\ndata = yaml.load(open('cfg.yml'))\n"
        (tmp_path / "deep.py").write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        matching = [
            f for f in report.findings if f.pattern_name == "python_yaml_unsafe"
        ]
        finding = matching[0]
        assert finding.line == 3
        hunk_line = finding.fix_diff.splitlines()[2]
        assert "@@ -3,1 +3,1 @@" in hunk_line

    def test_mixed_file_some_with_some_without_template(
        self, tmp_path: Path,
    ) -> None:
        """A single file triggering both template and non-template patterns."""
        # "result = eval(...)" triggers python_dynamic_eval (no template)
        # "yaml.load(...)" triggers python_yaml_unsafe (has template)
        code = (
            "result = eval(user_input)\n"  # noqa: S307 — test fixture
            "data = yaml.load(open('f'))\n"
        )
        (tmp_path / "mixed.py").write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        eval_findings = [
            f for f in report.findings if f.pattern_name == "python_dynamic_eval"
        ]
        yaml_findings = [
            f for f in report.findings if f.pattern_name == "python_yaml_unsafe"
        ]
        assert eval_findings and eval_findings[0].fix_diff == ""
        assert yaml_findings and yaml_findings[0].fix_diff != ""


# ---------------------------------------------------------------------------
# TestFormatReportAutofix
# ---------------------------------------------------------------------------


class TestFormatReportAutofix:
    """Tests for autofix display in format_report."""

    def test_format_report_includes_autofix_section(
        self, tmp_path: Path,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS["python_shell_true"]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        text = scanner.format_report(report)
        assert "Autofix:" in text

    def test_format_report_includes_diff_lines(
        self, tmp_path: Path,
    ) -> None:
        filename, code, _ = _VULNERABLE_SNIPPETS["python_shell_true"]
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        text = scanner.format_report(report)
        # The diff lines should be indented in the report
        assert "--- a/" in text
        assert "+++ b/" in text

    def test_format_report_omits_autofix_when_no_diff(
        self, tmp_path: Path,
    ) -> None:
        filename, code = _NO_TEMPLATE_SNIPPET
        (tmp_path / filename).write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        # Filter findings to only those without fix_diff to avoid
        # other patterns in the file accidentally having autofix
        report.findings = [
            f for f in report.findings if f.pattern_name == "python_dynamic_eval"
        ]
        text = scanner.format_report(report)
        assert "Autofix:" not in text

    def test_format_report_no_findings_no_autofix(
        self, tmp_path: Path,
    ) -> None:
        """An empty report should not mention Autofix at all."""
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")
        text = scanner.format_report(report)
        assert "Autofix:" not in text
        assert "No security issues found." in text

    def test_format_report_mixed_findings_only_shows_autofix_for_diffs(
        self, tmp_path: Path,
    ) -> None:
        """When some findings have fix_diff and others don't, only the ones
        with diffs should get the Autofix section."""
        # "result = eval(...)" triggers python_dynamic_eval (no template)
        # "yaml.load(...)" triggers python_yaml_unsafe (has template)
        code = (
            "result = eval(user_input)\n"  # noqa: S307 — test fixture
            "data = yaml.load(open('f'))\n"
        )
        (tmp_path / "both.py").write_text(code)
        scanner = SecurityScanner(root_dir=str(tmp_path))
        report = scanner.scan(mode="patterns")

        text = scanner.format_report(report)
        # Should contain at least one Autofix section (for yaml.load)
        assert text.count("Autofix:") >= 1
        # The eval finding should NOT have an Autofix block —
        # verify by checking that the eval recommendation line is NOT
        # followed by an Autofix line
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "Dynamic code evaluation" in line:
                # Look ahead: next non-empty content lines should not be Autofix
                for j in range(i + 1, min(i + 4, len(lines))):
                    if "Autofix:" in lines[j]:
                        # Make sure this Autofix is not right after the eval finding
                        # by checking that a different finding header appeared between
                        context_block = "\n".join(lines[i:j + 1])
                        if "yaml" not in context_block.lower():
                            pytest.fail(
                                "Autofix appeared after eval finding, which has no template"
                            )
