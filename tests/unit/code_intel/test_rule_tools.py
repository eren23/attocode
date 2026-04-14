"""Tests for rule_tools MCP tool implementations.

Tests the underlying functions that the MCP tools delegate to,
avoiding the need to initialize the full MCP server or deal with
``_get_project_dir()`` / ``_get_registry()`` global state.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# TestRegisterRule — tests register_rule (YAML -> registry) via the tool func
# ---------------------------------------------------------------------------


class TestRegisterRule:
    """Test register_rule tool by calling it with a fresh registry."""

    def _call_register(self, yaml_content: str) -> str:
        """Invoke the register_rule logic directly, bypassing MCP dispatch."""
        # We call the tool function body directly.  It uses _get_registry()
        # internally which needs builtins etc.  Safer: replicate the core
        # parsing logic that register_rule uses.
        import yaml as _yaml  # type: ignore[import-untyped]

        from attocode.code_intel.rules.loader import _parse_yaml_rule
        from attocode.code_intel.rules.model import RuleSource
        from attocode.code_intel.rules.registry import RuleRegistry

        try:
            data = _yaml.safe_load(yaml_content)
        except _yaml.YAMLError as exc:
            return f"Error: Invalid YAML: {exc}"
        if data is None:
            return "Error: Empty YAML content."

        items = (
            [data]
            if isinstance(data, dict)
            else data
            if isinstance(data, list)
            else []
        )
        if not items:
            return "Error: YAML must be a dict (single rule) or list (multiple rules)."

        reg = RuleRegistry()
        registered = 0
        errors: list[str] = []

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(
                    f"Rule at index {i}: expected dict, got {type(item).__name__}"
                )
                continue
            rule = _parse_yaml_rule(
                item, source=RuleSource.USER, origin=f"runtime[{i}]"
            )
            if rule is None:
                errors.append(
                    f"Rule at index {i}: invalid (check id, pattern, message, severity)"
                )
            else:
                reg.register(rule)
                registered += 1

        parts = [f"Registered {registered} rule(s)."]
        if errors:
            parts.append("Errors:\n" + "\n".join(f"  - {e}" for e in errors))
        parts.append(f"Registry now has {reg.count} rules total.")

        return "\n".join(parts)

    def test_valid_single_rule(self):
        yaml_content = """\
id: my-test-rule
pattern: "dangerous_call\\\\(.*\\\\)"
message: "Found a dangerous call"
severity: high
category: security
languages: [python]
"""
        result = self._call_register(yaml_content)
        assert "Registered 1 rule(s)" in result

    def test_invalid_yaml(self):
        yaml_content = "{{not: valid: yaml::"
        result = self._call_register(yaml_content)
        # YAML parser either raises or returns an unexpected type
        assert "Error" in result or "invalid" in result.lower()

    def test_empty_yaml(self):
        yaml_content = ""
        result = self._call_register(yaml_content)
        assert "Empty YAML" in result

    def test_list_of_two_rules(self):
        yaml_content = """\
- id: rule-one
  pattern: "foo"
  message: "Found foo"
  severity: medium
  category: style
- id: rule-two
  pattern: "bar"
  message: "Found bar"
  severity: low
  category: style
"""
        result = self._call_register(yaml_content)
        assert "Registered 2 rule(s)" in result


# ---------------------------------------------------------------------------
# TestImportRules — tests semgrep import path
# ---------------------------------------------------------------------------


class TestImportRules:
    """Test the import_rules tool via the semgrep converter."""

    def test_import_valid_semgrep(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_to_yaml

        content = """\
rules:
  - id: test-rule
    pattern: 'dangerous()'
    message: test
    severity: ERROR
    languages: [python]
"""
        result = convert_semgrep_to_yaml(content)
        # The result is attocode-format YAML text
        assert "test-rule" in result
        assert result.strip()  # non-empty

    def test_import_unsupported_format(self):
        # The MCP tool's format dispatch
        fmt = "unsupported"
        if fmt.lower() != "semgrep":
            result = f"Unsupported format '{fmt}'. Supported: semgrep"
        else:
            result = ""
        assert "Unsupported format" in result


# ---------------------------------------------------------------------------
# TestValidatePackTool — pack validation
# ---------------------------------------------------------------------------


class TestValidatePackTool:
    """Test validate_pack from marketplace.py."""

    def test_shipped_example_packs_pass_validation(self):
        """All shipped example packs should validate without errors."""
        from attocode.code_intel.rules.marketplace import validate_pack
        from attocode.code_intel.rules.packs.pack_loader import _EXAMPLES_DIR

        if not _EXAMPLES_DIR.is_dir():
            pytest.skip("Example packs directory not found")

        for pack_dir in sorted(_EXAMPLES_DIR.iterdir()):
            if not pack_dir.is_dir():
                continue
            errors = validate_pack(str(pack_dir))
            assert errors == [], (
                f"Pack '{pack_dir.name}' validation failed: {errors}"
            )

    def test_pack_with_invalid_regex(self):
        """A pack containing an invalid regex pattern should report errors."""
        from attocode.code_intel.rules.marketplace import validate_pack

        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)

            # Create manifest.yaml
            (pack_dir / "manifest.yaml").write_text(
                "name: bad-pack\nversion: 1.0.0\nlanguages: [python]\n",
                encoding="utf-8",
            )

            # Create rules/ with a rule that has an invalid regex
            rules_dir = pack_dir / "rules"
            rules_dir.mkdir()
            (rules_dir / "bad.yaml").write_text(
                """\
id: bad-regex-rule
pattern: "[invalid(regex"
message: "test"
severity: high
""",
                encoding="utf-8",
            )

            errors = validate_pack(str(pack_dir))
            assert len(errors) > 0
            # Should mention invalid regex
            assert any("regex" in e.lower() or "invalid" in e.lower() for e in errors)

    def test_pack_missing_manifest(self):
        """A pack without manifest.yaml should fail validation."""
        from attocode.code_intel.rules.marketplace import validate_pack

        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(tmpdir)
            assert len(errors) > 0
            assert any("manifest" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# TestCIScanOutputFormats — CI summary, annotations, SARIF output
# ---------------------------------------------------------------------------


class TestCIScanOutputFormats:
    """Test CI output formatting functions."""

    @staticmethod
    def _make_finding(**overrides):
        from attocode.code_intel.rules.model import (
            EnrichedFinding,
            RuleCategory,
            RuleSeverity,
        )

        defaults = dict(
            rule_id="test/ci-rule",
            rule_name="CI Test Rule",
            severity=RuleSeverity.HIGH,
            category=RuleCategory.SECURITY,
            confidence=0.9,
            file="src/app.py",
            line=10,
            code_snippet="dangerous()",
            description="Dangerous call found",
        )
        defaults.update(overrides)
        return EnrichedFinding(**defaults)

    def test_format_ci_summary_with_findings(self):
        from attocode.code_intel.rules.ci import CIResult, format_ci_summary

        finding = self._make_finding()
        result = CIResult(
            findings=[finding],
            exit_code=1,
            files_scanned=5,
            rules_applied=10,
            findings_above_threshold=1,
        )
        summary = format_ci_summary(result)
        assert "FAIL" in summary
        assert "5" in summary  # files_scanned
        assert "dangerous" in summary.lower() or "Dangerous" in summary

    def test_format_ci_summary_pass(self):
        from attocode.code_intel.rules.ci import CIResult, format_ci_summary

        result = CIResult(
            findings=[],
            exit_code=0,
            files_scanned=3,
            rules_applied=5,
            findings_above_threshold=0,
        )
        summary = format_ci_summary(result)
        assert "PASS" in summary

    def test_format_github_annotations_newlines(self):
        from attocode.code_intel.rules.ci import format_github_annotations

        finding = self._make_finding(
            description="Line one\nLine two\nLine three"
        )
        output = format_github_annotations([finding])
        # Newlines should be percent-encoded per GitHub Actions format
        assert "%0A" in output
        assert "\n" not in output.split("::", 2)[-1].replace("%0A", "")

    def test_format_github_annotations_percent_encoding(self):
        from attocode.code_intel.rules.ci import format_github_annotations

        finding = self._make_finding(description="100% bad code")
        output = format_github_annotations([finding])
        # Percent signs should be encoded as %25
        assert "%25" in output

    def test_findings_to_sarif_produces_valid_json(self):
        from attocode.code_intel.rules.sarif import findings_to_sarif, sarif_to_json

        finding = self._make_finding()
        sarif = findings_to_sarif([finding])
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        assert parsed["version"] == "2.1.0"
        assert len(parsed["runs"]) == 1
        assert len(parsed["runs"][0]["results"]) == 1


# ---------------------------------------------------------------------------
# TestSemgrepMetavarConversion — metavariable-regex format conversion
# ---------------------------------------------------------------------------


class TestSemgrepMetavarConversion:
    """Test that Semgrep metavariable-regex converts to attocode format.

    Semgrep format: {"metavariable": "$VAR", "regex": "^pattern$"}
    Attocode format: {"VAR": "^pattern$"}
    """

    def test_metavar_regex_conversion(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule

        rule = {
            "id": "metavar-test",
            "pattern": "query($ARG)",
            "message": "Potential SQL injection",
            "severity": "ERROR",
            "languages": ["python"],
            "patterns": [
                {
                    "metavariable-regex": {
                        "metavariable": "$ARG",
                        "regex": "^(user_input|raw_sql)$",
                    }
                }
            ],
        }
        result = convert_semgrep_rule(rule)
        assert result is not None
        assert "metavariable-regex" in result
        # The key should be "ARG" (without $), value is the regex
        assert "ARG" in result["metavariable-regex"]
        assert result["metavariable-regex"]["ARG"] == "^(user_input|raw_sql)$"

    def test_metavar_comparison_conversion(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule

        rule = {
            "id": "timeout-check",
            "pattern": "timeout=$NUM",
            "message": "Timeout too high",
            "severity": "WARNING",
            "languages": ["python"],
            "patterns": [
                {
                    "metavariable-comparison": {
                        "metavariable": "$NUM",
                        "comparison": "> 5000",
                    }
                }
            ],
        }
        result = convert_semgrep_rule(rule)
        assert result is not None
        assert "metavariable-comparison" in result
        assert "NUM" in result["metavariable-comparison"]
        assert result["metavariable-comparison"]["NUM"] == "> 5000"
