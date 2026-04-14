"""Tests for community rule marketplace and Semgrep importer."""
# nosec — test file contains intentional insecure pattern strings for testing

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.rules.marketplace import (
    RegistryEntry,
    format_registry_search,
    prepare_pack_for_publish,
    validate_pack,
)


class TestValidatePack:
    def _make_pack(self, tmpdir: str, rules_yaml: str = "", manifest_yaml: str = "") -> str:
        pack_dir = Path(tmpdir) / "test-pack"
        pack_dir.mkdir()
        rules_dir = pack_dir / "rules"
        rules_dir.mkdir()

        if not manifest_yaml:
            manifest_yaml = "name: test-pack\nversion: 1.0.0\nlanguages: [python]\n"
        (pack_dir / "manifest.yaml").write_text(manifest_yaml)

        if not rules_yaml:
            rules_yaml = (
                "- id: test-rule\n"
                "  pattern: 'bad_pattern\\('\n"
                "  message: 'Bad pattern detected'\n"
                "  severity: medium\n"
            )
        (rules_dir / "rules.yaml").write_text(rules_yaml)

        return str(pack_dir)

    def test_valid_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir))
            assert errors == []

    def test_missing_rules_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "pack"
            pack_dir.mkdir()
            (pack_dir / "manifest.yaml").write_text("name: x\n")
            errors = validate_pack(str(pack_dir))
            assert any("rules/" in e for e in errors)

    def test_invalid_regex(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir, rules_yaml=(
                "- id: bad-regex\n  pattern: '[invalid'\n  message: test\n  severity: high\n"
            )))
            assert any("invalid regex" in e.lower() for e in errors)

    def test_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir, rules_yaml=(
                "- id: dup\n  pattern: 'a'\n  message: t\n  severity: high\n"
                "- id: dup\n  pattern: 'b'\n  message: t\n  severity: low\n"
            )))
            assert any("duplicate" in e.lower() for e in errors)

    def test_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir, rules_yaml=(
                "- id: no-msg\n  pattern: 'x'\n  severity: high\n"
            )))
            assert any("message" in e for e in errors)

    def test_inline_test_cases_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir, rules_yaml=(
                "- id: tested\n  pattern: 'danger\\('\n  message: d\n  severity: high\n"
                "  test_cases:\n"
                "    - code: 'danger(x)'\n      should_match: true\n"
                "    - code: 'safe(x)'\n      should_match: false\n"
            )))
            assert errors == []

    def test_inline_test_cases_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = validate_pack(self._make_pack(tmpdir, rules_yaml=(
                "- id: failing\n  pattern: 'danger\\('\n  message: d\n  severity: high\n"
                "  test_cases:\n    - code: 'safe(x)'\n      should_match: true\n"
            )))
            assert any("expected match" in e for e in errors)

    def test_existing_example_packs_valid(self):
        examples_dir = Path("src/attocode/code_intel/rules/packs/examples")
        for pack_dir in sorted(examples_dir.iterdir()):
            if pack_dir.is_dir():
                errors = validate_pack(str(pack_dir))
                assert errors == [], f"Pack {pack_dir.name} failed: {errors}"


class TestFormatRegistrySearch:
    def test_empty(self):
        assert "No packs found" in format_registry_search([])

    def test_with_entries(self):
        result = format_registry_search([RegistryEntry(
            name="owasp", url="https://x", languages=["python"],
            rules_count=42, description="OWASP patterns",
        )])
        assert "owasp" in result
        assert "42 rules" in result


class TestSemgrepImporter:
    def test_simple_pattern(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        result = convert_semgrep_rule({
            "id": "test", "pattern": "subprocess.call($CMD)",
            "message": "injection", "severity": "ERROR",
            "languages": ["python"], "metadata": {"cwe": "CWE-78"},
        })
        assert result is not None
        assert result["severity"] == "high"
        assert result["cwe"] == "CWE-78"

    def test_pattern_either(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        result = convert_semgrep_rule({
            "id": "hash", "pattern-either": [
                {"pattern": "hashlib.md5()"}, {"pattern": "hashlib.sha1()"},
            ], "message": "weak", "severity": "WARNING", "languages": ["python"],
        })
        assert result is not None
        assert len(result["pattern-either"]) == 2

    def test_composite_patterns(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        result = convert_semgrep_rule({
            "id": "comp", "patterns": [
                {"pattern": "dangerous($X)"}, {"pattern-not-inside": "safe($X)"},
            ], "message": "risk", "severity": "ERROR", "languages": ["python"],
        })
        assert result is not None
        assert len(result["patterns"]) == 2

    def test_severity_mapping(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        for sev, expected in [("ERROR", "high"), ("WARNING", "medium"), ("INFO", "low")]:
            r = convert_semgrep_rule({"id": sev, "pattern": "x", "message": "t", "severity": sev, "languages": ["py"]})
            assert r["severity"] == expected

    def test_batch_conversion(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_file
        converted, errors = convert_semgrep_file(
            "rules:\n  - id: r1\n    pattern: 'a'\n    message: m\n    severity: ERROR\n    languages: [py]\n"
            "  - id: r2\n    pattern: 'b'\n    message: m\n    severity: WARNING\n    languages: [py]\n"
        )
        assert len(converted) == 2
        assert not errors

    def test_no_pattern_returns_none(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        assert convert_semgrep_rule({"id": "x", "message": "t", "severity": "ERROR"}) is None

    def test_fix_preserved(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule
        r = convert_semgrep_rule({
            "id": "fix", "pattern": "old($A)", "message": "m",
            "severity": "WARNING", "languages": ["py"], "fix": "new($A)",
        })
        assert r["fix"]["replace"] == "new($A)"

    def test_cwe_extraction(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_cwe
        assert _extract_cwe({"cwe": "CWE-89"}) == "CWE-89"
        assert _extract_cwe({"cwe": ["CWE-78"]}) == "CWE-78"
        assert _extract_cwe({}) == ""
