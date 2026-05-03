"""Tests for the Tier-2 ast-grep structural rule executor."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from attocode.code_intel.rules.executor import (
    _ast_grep_available,
    _execute_structural_rule,
    execute_rules,
)
from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)


def _structural_rule(
    rule_id: str,
    pattern: str,
    *,
    languages: list[str] | None = None,
    description: str = "matched: $X",
) -> UnifiedRule:
    return UnifiedRule(
        id=rule_id,
        name=rule_id,
        description=description,
        severity=RuleSeverity.HIGH,
        category=RuleCategory.SECURITY,
        languages=list(languages or []),
        structural_pattern=pattern,
        source=RuleSource.USER,
        tier=RuleTier.STRUCTURAL,
        pack="test",
    )


def _regex_rule(rule_id: str, pattern: str, *, languages: list[str] | None = None) -> UnifiedRule:
    return UnifiedRule(
        id=rule_id,
        name=rule_id,
        description="regex hit",
        severity=RuleSeverity.MEDIUM,
        category=RuleCategory.SUSPICIOUS,
        languages=list(languages or []),
        pattern=re.compile(pattern),
        source=RuleSource.USER,
        tier=RuleTier.REGEX,
        pack="test",
    )


needs_ast_grep = pytest.mark.skipif(
    not _ast_grep_available(),
    reason="ast-grep binary (sg / ast-grep) not on PATH",
)


@pytest.fixture
def python_print_file(tmp_path: Path) -> Path:
    """Tiny Python file with a function that calls ``print`` — neutral
    pattern that ast-grep can match without tripping security hooks."""
    p = tmp_path / "sample.py"
    p.write_text(
        "def f(x):\n"
        "    print(x)  # leftover\n"
        "\n"
        "def g():\n"
        "    other_call()\n",
        encoding="utf-8",
    )
    return p


class TestStructuralExecutor:
    @needs_ast_grep
    def test_finds_match_with_metavar_capture(self, python_print_file: Path):
        rule = _structural_rule(
            "no-print", "print($X)", languages=["python"],
        )
        findings = _execute_structural_rule(
            rule,
            files_by_lang={"python": [str(python_print_file)]},
            project_dir=str(python_print_file.parent),
        )
        assert len(findings) == 1, findings
        f = findings[0]
        assert f.rule_id == "test/no-print"
        assert f.line == 2  # 1-based
        assert "x" in f.captures.get("X", ""), f.captures
        assert "matched: x" in f.description

    @needs_ast_grep
    def test_no_match_when_pattern_absent(self, tmp_path: Path):
        clean = tmp_path / "clean.py"
        clean.write_text("def f(): return 1\n", encoding="utf-8")
        rule = _structural_rule("no-print", "print($X)", languages=["python"])
        findings = _execute_structural_rule(
            rule, files_by_lang={"python": [str(clean)]},
        )
        assert findings == []

    def test_skips_unsupported_language(self, tmp_path: Path):
        # Make up a language ast-grep does not support so the rule's
        # entire-language list is filtered out and no subprocess fires.
        f = tmp_path / "x.unknown"
        f.write_text("anything\n", encoding="utf-8")
        rule = _structural_rule("x", "any($X)", languages=["nim"])
        findings = _execute_structural_rule(
            rule, files_by_lang={"nim": [str(f)]},
        )
        assert findings == []

    def test_empty_pattern_returns_empty(self, tmp_path: Path):
        rule = _structural_rule("x", "", languages=["python"])
        findings = _execute_structural_rule(
            rule, files_by_lang={"python": [str(tmp_path / "x.py")]},
        )
        assert findings == []


class TestExecuteRulesIntegration:
    @needs_ast_grep
    def test_structural_and_regex_rules_run_together(self, python_print_file: Path):
        """Mixing tiers in one ``execute_rules`` call must produce findings
        from both the structural path and the regex path."""
        findings = execute_rules(
            files=[str(python_print_file)],
            rules=[
                _structural_rule(
                    "no-print", "print($X)", languages=["python"],
                ),
                _regex_rule("noisy-comment", r"# leftover"),
            ],
            project_dir=str(python_print_file.parent),
        )
        rule_ids = {f.rule_id for f in findings}
        assert "test/no-print" in rule_ids
        assert "test/noisy-comment" in rule_ids

    def test_missing_ast_grep_is_silent_skip(
        self, monkeypatch: pytest.MonkeyPatch, python_print_file: Path,
    ):
        """When ast-grep is missing, structural rules are silently skipped
        and regex rules still run."""
        from attocode.code_intel.rules import executor as ex

        monkeypatch.setattr(ex, "_ast_grep_available", lambda: False)
        findings = execute_rules(
            files=[str(python_print_file)],
            rules=[
                _structural_rule("no-print", "print($X)", languages=["python"]),
                _regex_rule("noisy-comment", r"# leftover"),
            ],
            project_dir=str(python_print_file.parent),
        )
        rule_ids = {f.rule_id for f in findings}
        assert "test/no-print" not in rule_ids
        assert "test/noisy-comment" in rule_ids


class TestUtilities:
    def test_ast_grep_available_reflects_path(self):
        # Just exercise the function — its return value is whatever the
        # current environment has on PATH.
        assert _ast_grep_available() in (True, False)
        if _ast_grep_available():
            assert shutil.which("sg") or shutil.which("ast-grep")


def _hybrid_rule(rule_id: str, *, languages: list[str]) -> UnifiedRule:
    """Structural rule that ALSO has a Tier-1 regex pattern as fallback."""
    return UnifiedRule(
        id=rule_id,
        name=rule_id,
        description="hybrid match",
        severity=RuleSeverity.MEDIUM,
        category=RuleCategory.SUSPICIOUS,
        languages=list(languages),
        pattern=re.compile(r"forbidden"),
        structural_pattern="print($X)",
        source=RuleSource.USER,
        tier=RuleTier.STRUCTURAL,
        pack="test",
    )


class TestStructuralFallback:
    """Roadmap Phase 1 line: 'Fallback to regex Tier 1 for languages without
    ast-grep grammars'. A structural rule with both ``structural_pattern``
    and ``pattern`` set should use ast-grep where supported and fall back
    to the regex for the rest."""

    def test_fallback_runs_regex_for_unsupported_language(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """Even when ast-grep is on PATH, a target language outside
        ``_AST_GREP_LANGS`` must still be matched via the regex pattern.
        We simulate this by removing 'python' from ``_AST_GREP_LANGS``
        for the test — every extension in the executor's detection map
        is currently ast-grep-supported, so this is the only way to
        exercise the per-language fallback codepath."""
        from attocode.code_intel.rules import executor as ex

        monkeypatch.setattr(
            ex, "_AST_GREP_LANGS",
            frozenset(ex._AST_GREP_LANGS - {"python"}),
        )

        py_file = tmp_path / "x.py"
        py_file.write_text("y = forbidden\n", encoding="utf-8")
        rule = _hybrid_rule("hybrid", languages=["python"])

        findings = execute_rules(
            files=[str(py_file)],
            rules=[rule],
            project_dir=str(tmp_path),
        )
        assert len(findings) == 1
        assert findings[0].rule_id == "test/hybrid"

    def test_fallback_runs_regex_when_ast_grep_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """When ast-grep is unavailable, structural rules with a regex
        pattern should run via the regex path for ALL their target
        languages — not be silently dropped."""
        from attocode.code_intel.rules import executor as ex

        monkeypatch.setattr(ex, "_ast_grep_available", lambda: False)

        py_file = tmp_path / "x.py"
        py_file.write_text("y = forbidden\n", encoding="utf-8")
        rule = _hybrid_rule("hybrid", languages=["python"])

        findings = execute_rules(
            files=[str(py_file)],
            rules=[rule],
            project_dir=str(tmp_path),
        )
        assert len(findings) == 1
        assert findings[0].rule_id == "test/hybrid"

    @needs_ast_grep
    def test_supported_language_uses_ast_grep_not_fallback(self, tmp_path: Path):
        """When the language IS supported by ast-grep, the regex path must
        not also fire — otherwise rules would double-report."""
        py_file = tmp_path / "x.py"
        py_file.write_text(
            "print(value)  # struct match, no 'forbidden' here\n",
            encoding="utf-8",
        )
        rule = _hybrid_rule("hybrid", languages=["python"])

        findings = execute_rules(
            files=[str(py_file)],
            rules=[rule],
            project_dir=str(tmp_path),
        )
        # Only the structural match (print) should fire — no regex hit
        # since 'forbidden' isn't present.
        assert len(findings) == 1
        assert findings[0].rule_id == "test/hybrid"
        assert "value" in findings[0].captures.get("X", "")

    @needs_ast_grep
    def test_analyze_end_to_end_picks_up_user_structural_rule(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """Full path: ATTOCODE_PROJECT_DIR → _get_registry loads user YAML
        rule → _analyze_impl runs execute_rules → structural finding lands
        in the formatted output. Catches wiring bugs the unit-level tests
        can't see."""
        # Source file with the pattern we'll match.
        src = tmp_path / "src.py"
        src.write_text(
            "def f(x):\n    print(x)  # leftover\n", encoding="utf-8",
        )

        # User rule in .attocode/rules/.
        rules_dir = tmp_path / ".attocode" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test.yaml").write_text(
            "- id: e2e-no-print\n"
            "  name: e2e-no-print\n"
            "  description: 'matched: $X'\n"
            "  structural_pattern: 'print($X)'\n"
            "  severity: high\n"
            "  category: security\n"
            "  languages: [python]\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
        # Force registry rebuild so the user rule is picked up.
        from attocode.code_intel.tools import rule_tools as rt

        monkeypatch.setattr(rt, "_registry", None)
        monkeypatch.setattr(rt, "_registry_loaded", False)

        out = rt._analyze_impl(
            path="", project_dir=str(tmp_path), min_confidence=0.0,
        )
        assert "e2e-no-print" in out, out
        assert "src.py" in out

    @needs_ast_grep
    def test_pack_structural_rules_load_and_fire_new_packs(self, tmp_path: Path):
        """A5 — every newly added pack ships ≥3 structural rules and each
        rule fires on a hand-rolled positive fixture."""
        from attocode.code_intel.rules.executor import execute_rules
        from attocode.code_intel.rules.packs.pack_loader import (
            list_example_packs, load_pack,
        )

        fixtures = {
            "cpp": ("app.cpp",
                "#include <cstdio>\n"
                "#include <iostream>\n"
                "int weird(double x) {\n"
                "    printf(\"%f\", x);\n"
                "    std::cout << x;\n"
                "    return (int)x;\n"
                "}\n"),
            "csharp": ("App.cs",
                "class App {\n"
                "    void handle() {\n"
                "        Console.WriteLine(\"hi\");\n"
                "        throw new Exception(\"boom\");\n"
                "        var s = string.Format(\"x={0}\", 1);\n"
                "    }\n"
                "}\n"),
            "php": ("app.php",
                "<?php\n"
                "function handle($x) {\n"
                "    var_dump($x);\n"
                "    print_r($x);\n"
                "    die(\"stop\");\n"
                "}\n"),
            "ruby": ("app.rb",
                "def handle(x)\n"
                "  puts x\n"
                "  pp x\n"
                "  binding.pry\n"
                "end\n"),
            "kotlin": ("App.kt",
                "fun handle() {\n"
                "    TODO()\n"
                "    System.out.println(\"hi\")\n"
                "    try { f() } catch (e: Exception) {}\n"
                "}\n"
                "fun f() {}\n"),
        }

        packs_by_name = {ex.name: ex for ex in list_example_packs()}
        for pack_name, (filename, source) in fixtures.items():
            ex = packs_by_name.get(pack_name)
            assert ex is not None, f"missing example pack: {pack_name}"

            rules = load_pack(ex)
            structural_rules = [r for r in rules if r.tier.value == "structural"]
            assert len(structural_rules) >= 3, (
                f"{pack_name}: expected >=3 structural rules, got {len(structural_rules)}"
            )

            f = tmp_path / pack_name / filename
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(source, encoding="utf-8")

            findings = execute_rules(
                [str(f)], structural_rules, project_dir=str(tmp_path),
            )
            fired_ids = {fnd.rule_id for fnd in findings}
            expected_ids = {r.qualified_id for r in structural_rules}
            missing = expected_ids - fired_ids
            assert not missing, (
                f"{pack_name}: structural rules failed to fire: {missing}"
            )

    @needs_ast_grep
    def test_pack_structural_rules_load_and_fire(self, tmp_path: Path):
        """A4 — every example pack ships at least 3 structural rules and
        each rule fires on a hand-rolled positive fixture."""
        from attocode.code_intel.rules.executor import execute_rules
        from attocode.code_intel.rules.packs.pack_loader import (
            list_example_packs, load_pack,
        )

        # (lang, file_extension, source) — content that triggers every
        # structural rule we shipped for the pack.
        fixtures = {
            "python": ("app.py",
                "def handle(req):\n"
                "    print(req)\n"
                "    assert req\n"
                "    time.sleep(1)\n"),
            "go": ("app.go",
                "package main\n"
                "import \"fmt\"\n"
                "func handle() {\n"
                "    fmt.Println(\"hi\")\n"
                "    panic(\"boom\")\n"
                "    time.Sleep(1)\n"
                "}\n"),
            "typescript": ("app.ts",
                "function handle(x: any) {\n"
                "    console.log(x);\n"
                "    const y = x!;\n"
                "    setTimeout(() => {}, 0);\n"
                "}\n"),
            "rust": ("app.rs",
                "fn handle(x: Option<i32>) {\n"
                "    let y = x.expect(\"required\");\n"
                "    dbg!(y);\n"
                "    println!(\"hi\");\n"
                "}\n"),
            "java": ("App.java",
                "class App {\n"
                "    void handle(Exception e) {\n"
                "        System.out.println(\"hi\");\n"
                "        e.printStackTrace();\n"
                "        Thread.sleep(1);\n"
                "    }\n"
                "}\n"),
        }

        packs_by_name = {ex.name: ex for ex in list_example_packs()}
        for pack_name, (filename, source) in fixtures.items():
            ex = packs_by_name.get(pack_name)
            assert ex is not None, f"missing example pack: {pack_name}"

            rules = load_pack(ex)
            structural_rules = [r for r in rules if r.tier.value == "structural"]
            assert len(structural_rules) >= 3, (
                f"{pack_name}: expected >=3 structural rules, got {len(structural_rules)}"
            )

            f = tmp_path / pack_name / filename
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(source, encoding="utf-8")

            findings = execute_rules(
                [str(f)], structural_rules, project_dir=str(tmp_path),
            )
            fired_ids = {fnd.rule_id for fnd in findings}
            expected_ids = {r.qualified_id for r in structural_rules}
            missing = expected_ids - fired_ids
            assert not missing, (
                f"{pack_name}: structural rules failed to fire: {missing}"
            )

    @needs_ast_grep
    def test_idiomatic_cli_code_does_not_fire_debug_rules_at_default_threshold(
        self, tmp_path: Path,
    ):
        """N6 — idiomatic CLI scripts use ``print`` / ``fmt.Println`` etc.
        as the actual interface. After H1, those rules are tagged
        ``debug`` and confidence-dropped below the default threshold,
        so a vanilla ``analyze(min_confidence=0.5)`` over a CLI fixture
        should not produce noise.

        Validates that we don't ship a configuration where every CLI
        repository sees false-positives on first scan."""
        from attocode.code_intel.rules.executor import execute_rules
        from attocode.code_intel.rules.filters.pipeline import run_pipeline
        from attocode.code_intel.rules.packs.pack_loader import (
            list_example_packs, load_pack,
        )

        cli_fixtures = {
            "cli.py": (
                "\"\"\"Tiny CLI tool.\"\"\"\n"
                "import sys\n"
                "def main():\n"
                "    print(\"Usage: foo <arg>\")\n"
                "    sys.exit(1)\n"
            ),
            "cli.go": (
                "package main\n"
                "import \"fmt\"\n"
                "func main() {\n"
                "    fmt.Println(\"hello\")\n"
                "}\n"
            ),
            "cli.ts": (
                "function main() {\n"
                "    console.log(\"usage\")\n"
                "}\n"
            ),
        }
        for name, content in cli_fixtures.items():
            (tmp_path / name).write_text(content, encoding="utf-8")

        all_rules = []
        for ex in list_example_packs():
            all_rules.extend(load_pack(ex))

        files = [str(tmp_path / n) for n in cli_fixtures]
        findings = execute_rules(files, all_rules, project_dir=str(tmp_path))
        # Apply the default ``analyze`` confidence threshold.
        findings = run_pipeline(findings, min_confidence=0.5)

        debug_findings = [
            f for f in findings
            if any(kw in f.rule_id for kw in ("print", "console", "println", "debug"))
        ]
        assert debug_findings == [], (
            "default-threshold analyze should not flag idiomatic CLI prints; "
            f"got {[(f.rule_id, f.file, f.line) for f in debug_findings]}"
        )

    def test_inline_rule_yaml_runtime_rejects_context_without_selector(self):
        """Review I3 — programmatic UnifiedRule with context but no
        selector reaches ``_build_inline_rule_yaml`` even though the
        loader rejects pack-loaded rules in this shape. The runtime path
        must fail loudly, not silently emit invalid ast-grep YAML."""
        from attocode.code_intel.rules.executor import _build_inline_rule_yaml

        bad = UnifiedRule(
            id="r",
            name="r",
            description="m",
            severity=RuleSeverity.LOW,
            category=RuleCategory.STYLE,
            languages=["go"],
            structural_pattern="fmt.Println($X)",
            structural_context="func _() { fmt.Println($X) }",
            structural_selector="",  # the bug: missing
            source=RuleSource.USER,
            tier=RuleTier.STRUCTURAL,
        )
        with pytest.raises(ValueError, match="structural_selector"):
            _build_inline_rule_yaml(bad, "go")

    def test_yaml_quote_handles_newlines_and_quotes(self):
        """Review I1 — synthesised / evolved patterns may contain
        newlines or double-quotes. The double-quoted-with-escapes form
        must round-trip via ``yaml.safe_load``."""
        import yaml

        from attocode.code_intel.rules.executor import _yaml_quote

        for raw in (
            'simple',
            "with 'single' quotes",
            'with "double" quotes',
            'multi\nline\npattern',
            'tab\there',
            r'backslash\d+',
        ):
            quoted = _yaml_quote(raw)
            decoded = yaml.safe_load(quoted)
            assert decoded == raw, (raw, quoted, decoded)

    def test_loader_rejects_context_without_selector(self):
        """I4 — a YAML rule that sets ``structural_context`` but omits
        ``structural_selector`` produces invalid ast-grep YAML at runtime.
        The loader must reject it cleanly instead of letting the rule
        silently no-op when scanned."""
        from attocode.code_intel.rules.loader import _parse_yaml_rule
        from attocode.code_intel.rules.model import RuleSource

        rule = _parse_yaml_rule(
            {
                "id": "broken",
                "message": "x",
                "severity": "low",
                "category": "style",
                "languages": ["go"],
                "structural_pattern": "fmt.Println($X)",
                "structural_context": "func _() { fmt.Println($X) }",
                # structural_selector omitted on purpose
            },
            source=RuleSource.USER,
            origin="test",
        )
        assert rule is None

    def test_universal_structural_rule_no_double_run_with_ast_grep(
        self, tmp_path: Path,
    ):
        """A universal (no languages) structural rule with a pattern should
        NOT additionally run the regex path when ast-grep is available."""
        rule = UnifiedRule(
            id="universal",
            name="universal",
            description="m",
            severity=RuleSeverity.LOW,
            category=RuleCategory.STYLE,
            languages=[],  # universal
            pattern=re.compile(r"forbidden"),
            structural_pattern="print($X)",
            source=RuleSource.USER,
            tier=RuleTier.STRUCTURAL,
            pack="test",
        )
        py_file = tmp_path / "x.py"
        py_file.write_text("y = forbidden\n", encoding="utf-8")

        findings = execute_rules(
            files=[str(py_file)],
            rules=[rule],
            project_dir=str(tmp_path),
        )
        if _ast_grep_available():
            # ast-grep handled it (universal); no regex fallback fires
            # because the file has no `print()`. Zero findings.
            assert findings == []
        else:
            # No ast-grep — regex covers the universal rule.
            assert len(findings) == 1
