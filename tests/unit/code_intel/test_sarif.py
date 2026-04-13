"""Tests for SARIF v2.1.0 output formatter."""

from __future__ import annotations

import json

import pytest

from attocode.code_intel.rules.model import (
    EnrichedFinding,
    FewShotExample,
    RuleCategory,
    RuleSeverity,
)
from attocode.code_intel.rules.sarif import findings_to_sarif, sarif_to_json


def _make_finding(**overrides) -> EnrichedFinding:
    defaults = dict(
        rule_id="test/rule-1",
        rule_name="Test Rule",
        severity=RuleSeverity.HIGH,
        category=RuleCategory.SECURITY,
        confidence=0.9,
        file="src/app.py",
        line=42,
        code_snippet="dangerous_call()",
        description="Dangerous call detected",
    )
    defaults.update(overrides)
    return EnrichedFinding(**defaults)


class TestFindingsToSarif:
    def test_empty_findings(self):
        sarif = findings_to_sarif([])
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["rules"] == []

    def test_single_finding(self):
        sarif = findings_to_sarif([_make_finding()])
        run = sarif["runs"][0]
        assert len(run["results"]) == 1
        assert len(run["tool"]["driver"]["rules"]) == 1

    def test_severity_mapping(self):
        for sev, expected_level in [
            (RuleSeverity.CRITICAL, "error"),
            (RuleSeverity.HIGH, "error"),
            (RuleSeverity.MEDIUM, "warning"),
            (RuleSeverity.LOW, "note"),
            (RuleSeverity.INFO, "note"),
        ]:
            sarif = findings_to_sarif([_make_finding(severity=sev)])
            assert sarif["runs"][0]["results"][0]["level"] == expected_level

    def test_cwe_relationship(self):
        sarif = findings_to_sarif([_make_finding(cwe="CWE-89")])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "relationships" in rule
        assert rule["relationships"][0]["target"]["id"] == "CWE-89"

    def test_no_cwe_no_relationship(self):
        sarif = findings_to_sarif([_make_finding(cwe="")])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "relationships" not in rule

    def test_few_shot_examples_in_property_bag(self):
        sarif = findings_to_sarif([_make_finding(
            examples=[FewShotExample(
                bad_code="dangerous(x)",
                good_code="safe(x)",
                explanation="Use safe alternative",
            )],
        )])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "fewShotExamples" in rule["properties"]
        assert rule["properties"]["fewShotExamples"][0]["bad"] == "dangerous(x)"

    def test_dedup_rules_for_same_rule_id(self):
        sarif = findings_to_sarif([
            _make_finding(rule_id="rule-1", line=10),
            _make_finding(rule_id="rule-1", line=20),
        ])
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 1
        assert len(run["results"]) == 2
        assert run["results"][0]["ruleIndex"] == 0
        assert run["results"][1]["ruleIndex"] == 0

    def test_multiple_different_rules(self):
        sarif = findings_to_sarif([
            _make_finding(rule_id="rule-a"),
            _make_finding(rule_id="rule-b"),
        ])
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 2

    def test_uri_uses_forward_slashes(self):
        sarif = findings_to_sarif([_make_finding(file="src\\main\\app.py")])
        uri = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert "\\" not in uri
        assert "src/main/app.py" == uri

    def test_tool_version(self):
        sarif = findings_to_sarif([], tool_version="1.2.3")
        assert sarif["runs"][0]["tool"]["driver"]["version"] == "1.2.3"

    def test_captures_in_properties(self):
        sarif = findings_to_sarif([_make_finding(
            captures={"FUNC": "dangerous"},
        )])
        props = sarif["runs"][0]["results"][0]["properties"]
        assert props["captures"] == {"FUNC": "dangerous"}

    def test_help_with_explanation_and_recommendation(self):
        sarif = findings_to_sarif([_make_finding(
            explanation="Why this matters",
            recommendation="How to fix",
        )])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "Why this matters" in rule["help"]["markdown"]
        assert "How to fix" in rule["help"]["markdown"]


class TestSarifToJson:
    def test_valid_json(self):
        sarif = findings_to_sarif([_make_finding()])
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        assert parsed["version"] == "2.1.0"

    def test_indent(self):
        sarif = findings_to_sarif([])
        json_str = sarif_to_json(sarif, indent=4)
        assert "    " in json_str
