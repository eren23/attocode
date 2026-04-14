"""Integration tests for metavar and combinator rules through the full pipeline.

Tests the complete flow: YAML loading -> registry -> executor -> findings,
ensuring metavariables, composite patterns, and constraints work end-to-end.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.filters.pipeline import run_pipeline
from attocode.code_intel.rules.loader import load_yaml_rules
from attocode.code_intel.rules.model import RuleSource


class TestMetavarIntegration:
    def test_metavar_rule_with_constraints(self):
        """YAML rule with $FUNC + metavariable-regex constraint."""
        rule_yaml = (
            "- id: sql-concat\n"
            "  pattern: '$FUNC($STR + $VAR)'\n"
            "  message: '$FUNC called with string concat'\n"
            "  severity: high\n"
            "  category: security\n"
            "  languages: [python]\n"
            "  metavariable-regex:\n"
            "    FUNC: '^(query|execute)$'\n"
        )
        source = (
            "def bad():\n"
            '    query("SELECT " + user_id)\n'
            '    execute("DELETE " + table)\n'
            '    print("hello " + name)\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.py"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            assert len(rules) == 1
            assert rules[0].metavars == ["FUNC", "STR", "VAR"]
            assert rules[0].metavar_regex == {"FUNC": "^(query|execute)$"}

            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            # query and execute match, print does not (filtered by constraint)
            assert len(findings) == 2
            assert findings[0].captures["FUNC"] == "query"
            assert findings[1].captures["FUNC"] == "execute"
            # Description should be interpolated
            assert "query" in findings[0].description

    def test_metavar_autofix_resolution(self):
        """YAML rule with metavar-based fix template."""
        rule_yaml = (
            "- id: equalfold\n"
            "  pattern: 'strings.ToLower($EXPR) =='\n"
            "  message: 'Use EqualFold instead of ToLower comparison'\n"
            "  severity: medium\n"
            "  category: performance\n"
            "  languages: [go]\n"
            "  fix:\n"
            "    search: 'strings.ToLower($EXPR)'\n"
            "    replace: 'strings.EqualFold($EXPR, target)'\n"
        )
        source = 'package main\n\nfunc f() {\n    if strings.ToLower(name) == target {\n    }\n}\n'

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.go"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            assert rules[0].fix is not None
            assert rules[0].fix.uses_metavars is True

            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            assert len(findings) == 1
            # Fix should contain the resolved EXPR value
            assert "name" in findings[0].suggested_fix


class TestCombinatorIntegration:
    def test_pattern_inside_with_not(self):
        """Composite rule: pattern + pattern-inside + pattern-not."""
        rule_yaml = (
            "- id: sprintf-loop\n"
            "  patterns:\n"
            "    - pattern: 'fmt\\.Sprintf\\s*\\('\n"
            "    - pattern-inside: 'for\\s.*\\{'\n"
            "    - pattern-not: '// nolint'\n"
            "  message: 'Sprintf in loop'\n"
            "  severity: medium\n"
            "  category: performance\n"
            "  languages: [go]\n"
        )
        source = (
            "package main\n\n"
            "func bad() {\n"
            "    for i := 0; i < 10; i++ {\n"
            '        fmt.Sprintf("x")\n'
            "    }\n"
            "}\n\n"
            "func clean() {\n"
            '    fmt.Sprintf("y")\n'
            "}\n\n"
            "func suppressed() {\n"
            "    for i := 0; i < 10; i++ {\n"
            '        fmt.Sprintf("z") // nolint\n'
            "    }\n"
            "}\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.go"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            assert rules[0].composite_pattern is not None
            assert rules[0].pattern is None  # composite-only

            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            # Only the Sprintf inside the first loop (bad()) should match
            assert len(findings) == 1
            assert "Sprintf" in findings[0].code_snippet

    def test_pattern_either(self):
        """Top-level pattern-either rule."""
        rule_yaml = (
            "- id: weak-hash\n"
            "  pattern-either:\n"
            "    - 'md5\\.New\\('\n"
            "    - 'sha1\\.New\\('\n"
            "  message: 'Weak hash function'\n"
            "  severity: high\n"
            "  category: security\n"
            "  languages: [go]\n"
        )
        source = (
            "package main\n\n"
            "func f() {\n"
            "    md5.New()\n"
            "    sha1.New()\n"
            "    sha256.New()\n"
            "}\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.go"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            assert rules[0].composite_pattern is not None

            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            assert len(findings) == 2  # md5 + sha1, not sha256

    def test_pattern_not_inside(self):
        """Composite rule: match print only outside test functions."""
        rule_yaml = (
            "- id: print-outside-test\n"
            "  patterns:\n"
            "    - pattern: 'print\\('\n"
            "    - pattern-not-inside: 'def test_'\n"
            "  message: 'print outside test'\n"
            "  severity: low\n"
            "  category: style\n"
            "  languages: [python]\n"
        )
        source = (
            "def process():\n"
            '    print("debug")\n'
            "\n"
            "def test_example():\n"
            '    print("ok in test")\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.py"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            assert len(findings) == 1
            assert findings[0].line == 2  # process(), not test_example()

    def test_composite_only_rule_no_top_level_pattern(self):
        """Rule with only 'patterns:' key and no top-level 'pattern:'."""
        rule_yaml = (
            "- id: composite-only\n"
            "  patterns:\n"
            "    - pattern: 'TODO'\n"
            "    - pattern-not: 'FIXME'\n"
            "  message: 'TODO without FIXME'\n"
            "  severity: info\n"
            "  category: style\n"
            "  scan_comments: true\n"
        )
        source = "# TODO: clean this up\n# TODO FIXME: critical\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.py"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            assert rules[0].pattern is None
            assert rules[0].composite_pattern is not None

            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            # First line has TODO without FIXME, second has both
            assert len(findings) == 1
            assert findings[0].line == 1


class TestPipelineIntegration:
    def test_metavar_findings_survive_pipeline(self):
        """Ensure captures and interpolated descriptions survive the filter pipeline."""
        rule_yaml = (
            "- id: test-captures\n"
            "  pattern: '$FUNC($ARG)'\n"
            "  message: '$FUNC called'\n"
            "  severity: high\n"
            "  category: security\n"
            "  confidence: 0.9\n"
        )
        source = "foo(bar)\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()
            (rules_dir / "test.yaml").write_text(rule_yaml)
            src = Path(tmpdir) / "test.py"
            src.write_text(source)

            rules = load_yaml_rules(str(rules_dir))
            findings = execute_rules([str(src)], rules, project_dir=tmpdir)
            findings = run_pipeline(findings, min_confidence=0.5)

            assert len(findings) >= 1
            f = findings[0]
            assert f.captures.get("FUNC") == "foo"
            assert "foo" in f.description
