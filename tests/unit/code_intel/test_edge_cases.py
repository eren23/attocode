"""Edge-case tests for metavar, combinators, SARIF, and semgrep modules.

Covers boundary conditions and corner cases not exercised by the
primary test suites.
"""
from __future__ import annotations

import json
import re

import pytest

from attocode.code_intel.rules.metavar import (
    compile_metavar_pattern,
    has_metavars,
)
from attocode.code_intel.rules.combinators import (
    AllNode,
    EitherNode,
    MatchContext,
    RegexNode,
)
from attocode.code_intel.rules.model import (
    EnrichedFinding,
    RuleCategory,
    RuleSeverity,
)
from attocode.code_intel.rules.sarif import findings_to_sarif, sarif_to_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(line: str, line_no: int = 1, all_lines: list[str] | None = None) -> MatchContext:
    if all_lines is None:
        all_lines = [line]
    return MatchContext(line=line, line_no=line_no, all_lines=all_lines)


def _make_finding(**overrides) -> EnrichedFinding:
    defaults = dict(
        rule_id="edge/test-rule",
        rule_name="Edge Test Rule",
        severity=RuleSeverity.MEDIUM,
        category=RuleCategory.CORRECTNESS,
        confidence=0.8,
        file="src/edge.py",
        line=1,
        code_snippet="x = 1",
        description="Edge case finding",
    )
    defaults.update(overrides)
    return EnrichedFinding(**defaults)


# ---------------------------------------------------------------------------
# TestMetavarEdgeCases
# ---------------------------------------------------------------------------


class TestMetavarEdgeCases:
    """Boundary conditions for the metavariable module."""

    def test_has_metavars_empty_string(self):
        assert not has_metavars("")

    def test_compile_metavar_pattern_empty_string(self):
        """Empty pattern should compile without error (matches anything)."""
        pat, names = compile_metavar_pattern("")
        assert names == []
        # The compiled pattern is just an empty regex (matches empty string)
        assert pat.search("") is not None

    def test_has_metavars_bare_dollar(self):
        """A lone '$' sign without a following uppercase identifier is not a metavar."""
        assert not has_metavars("$")

    def test_has_metavars_dollar_digit(self):
        """'$100' starts with a digit after $, not a metavar."""
        assert not has_metavars("$100")

    def test_has_metavars_dollar_lowercase(self):
        """'$foo' starts with lowercase, not a metavar (our regex requires uppercase)."""
        assert not has_metavars("$foo")

    def test_compile_metavar_pattern_no_metavars(self):
        """Pattern without metavars should compile as plain escaped regex."""
        pat, names = compile_metavar_pattern("print()")
        assert names == []
        assert pat.search("print()")
        assert not pat.search("println()")

    def test_compile_metavar_pattern_special_chars_escaped(self):
        """Literal dots and parens in pattern should be escaped."""
        pat, names = compile_metavar_pattern("os.path.join($ARG)")
        assert "ARG" in names
        # The dot should be literal, not regex wildcard
        assert pat.search("os.path.join(foo)")
        assert not pat.search("os_path_join(foo)")


# ---------------------------------------------------------------------------
# TestCombinatorEdgeCases
# ---------------------------------------------------------------------------


class TestCombinatorEdgeCases:
    """Edge cases for boolean pattern combinators."""

    def test_either_node_with_captures(self):
        """EitherNode should propagate captures from the matching child."""
        node = EitherNode(children=[
            RegexNode(
                pattern=re.compile(r"(?P<FUNC>\w+)\(\)"),
                metavar_names=["FUNC"],
            ),
            RegexNode(pattern=re.compile("fallback")),
        ])
        ctx = _ctx("execute()")
        assert node.evaluate(ctx)
        assert ctx.captures.get("FUNC") == "execute"

    def test_either_node_second_child_captures(self):
        """When first child doesn't match, second child's captures populate."""
        node = EitherNode(children=[
            RegexNode(pattern=re.compile("no_match_here")),
            RegexNode(
                pattern=re.compile(r"(?P<NAME>\w+)\.run"),
                metavar_names=["NAME"],
            ),
        ])
        ctx = _ctx("server.run()")
        assert node.evaluate(ctx)
        assert ctx.captures.get("NAME") == "server"

    def test_all_node_short_circuit_captures(self):
        """AllNode: first child matches (populates captures), second fails.

        The AllNode should return False, but captures from the first
        child remain in the context (Python short-circuit still calls
        the generator up to the failing child).
        """
        node = AllNode(children=[
            RegexNode(
                pattern=re.compile(r"(?P<VAR>\w+)\s*="),
                metavar_names=["VAR"],
            ),
            RegexNode(pattern=re.compile("NEVER_MATCHES_ANYTHING_HERE")),
        ])
        ctx = _ctx("count = 42")
        result = node.evaluate(ctx)
        assert result is False
        # First child DID match and populated captures before second failed
        assert ctx.captures.get("VAR") == "count"

    def test_all_node_empty_children(self):
        """AllNode with no children should return True (vacuous truth)."""
        node = AllNode(children=[])
        assert node.evaluate(_ctx("anything"))

    def test_either_node_empty_children(self):
        """EitherNode with no children should return False."""
        node = EitherNode(children=[])
        assert not node.evaluate(_ctx("anything"))


# ---------------------------------------------------------------------------
# TestSarifEdgeCases
# ---------------------------------------------------------------------------


class TestSarifEdgeCases:
    """Edge cases for SARIF output formatting."""

    def test_findings_to_sarif_empty_captures(self):
        """Finding with captures={} (empty dict) should not crash."""
        finding = _make_finding(captures={})
        sarif = findings_to_sarif([finding])
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        # Empty captures should still be serializable
        props = parsed["runs"][0]["results"][0]["properties"]
        # captures key should not be present when empty (or present and empty)
        # The implementation includes captures only if truthy
        assert "captures" not in props or props["captures"] == {}

    def test_findings_to_sarif_line_zero(self):
        """Finding with line=0 should produce valid SARIF (edge case)."""
        finding = _make_finding(line=0)
        sarif = findings_to_sarif([finding])
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        region = parsed["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 0

    def test_findings_to_sarif_unicode_description(self):
        """Finding with unicode characters should serialize cleanly."""
        finding = _make_finding(description="Danger: \u26a0 found \u2014 fix it")
        sarif = findings_to_sarif([finding])
        json_str = sarif_to_json(sarif)
        parsed = json.loads(json_str)
        msg = parsed["runs"][0]["results"][0]["message"]["text"]
        assert "\u26a0" in msg

    def test_findings_to_sarif_no_function_name(self):
        """Finding without function_name should omit logicalLocations."""
        finding = _make_finding(function_name="")
        sarif = findings_to_sarif([finding])
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        assert "logicalLocations" not in loc

    def test_findings_to_sarif_with_function_name(self):
        """Finding with function_name should include logicalLocations."""
        finding = _make_finding(function_name="process_data")
        sarif = findings_to_sarif([finding])
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        assert "logicalLocations" in loc
        assert loc["logicalLocations"][0]["name"] == "process_data"

    def test_findings_to_sarif_suggested_fix_in_properties(self):
        """Suggested fix should appear in the result property bag."""
        finding = _make_finding(suggested_fix="Use safe_call() instead")
        sarif = findings_to_sarif([finding])
        props = sarif["runs"][0]["results"][0]["properties"]
        assert props["suggestedFix"] == "Use safe_call() instead"


# ---------------------------------------------------------------------------
# TestSemgrepEdgeCases
# ---------------------------------------------------------------------------


class TestSemgrepEdgeCases:
    """Edge cases for the Semgrep importer module."""

    def test_has_ast_metavars_with_ellipsis_and_dollar(self):
        from attocode.code_intel.rules.importers.semgrep import _has_ast_metavars

        assert _has_ast_metavars("func($X, ...)")

    def test_has_ast_metavars_no_ellipsis(self):
        from attocode.code_intel.rules.importers.semgrep import _has_ast_metavars

        # No ellipsis operator, just a dollar sign -- not AST-aware
        assert not _has_ast_metavars("subprocess.call($X)")

    def test_extract_confidence_float(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        assert _extract_confidence({"confidence": 0.9}) == 0.9

    def test_extract_confidence_string_high(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        assert _extract_confidence({"confidence": "high"}) == 0.9

    def test_extract_confidence_string_medium(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        assert _extract_confidence({"confidence": "medium"}) == 0.7

    def test_extract_confidence_string_low(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        assert _extract_confidence({"confidence": "low"}) == 0.5

    def test_extract_confidence_int_above_one_normalized(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        # Int > 1 should be normalized by dividing by 100
        result = _extract_confidence({"confidence": 95})
        assert result == 0.95

    def test_extract_confidence_no_key(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_confidence

        # No confidence key -> default
        assert _extract_confidence({}) == 0.8

    def test_convert_semgrep_to_yaml_valid_input(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_to_yaml

        content = """\
rules:
  - id: no-dangerous-call
    pattern: 'dangerous_fn()'
    message: "Do not use dangerous_fn"
    severity: ERROR
    languages: [python]
"""
        result = convert_semgrep_to_yaml(content)
        assert result.strip()  # non-empty
        assert "no-dangerous-call" in result

    def test_convert_semgrep_to_yaml_empty_rules(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_to_yaml

        content = "rules: []\n"
        result = convert_semgrep_to_yaml(content)
        # No rules to convert
        assert "No rules converted" in result or result.strip() == ""

    def test_extract_cwe_various_formats(self):
        from attocode.code_intel.rules.importers.semgrep import _extract_cwe

        assert _extract_cwe({"cwe": "CWE-89"}) == "CWE-89"
        assert _extract_cwe({"cwe": "cwe-79"}) == "CWE-79"
        assert _extract_cwe({"cwe": ["CWE-22", "CWE-78"]}) == "CWE-22"  # first
        assert _extract_cwe({"cwe": ""}) == ""
        assert _extract_cwe({}) == ""

    def test_severity_mapping(self):
        from attocode.code_intel.rules.importers.semgrep import _SEVERITY_MAP

        assert _SEVERITY_MAP["ERROR"] == "high"
        assert _SEVERITY_MAP["WARNING"] == "medium"
        assert _SEVERITY_MAP["INFO"] == "low"

    def test_convert_rule_no_id_returns_none(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule

        result = convert_semgrep_rule({"pattern": "foo", "message": "bar", "severity": "ERROR"})
        assert result is None

    def test_convert_rule_no_pattern_returns_none(self):
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_rule

        result = convert_semgrep_rule({"id": "test", "message": "bar", "severity": "ERROR"})
        assert result is None
