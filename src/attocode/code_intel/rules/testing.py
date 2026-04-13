"""Rule testing framework with inline annotations.

Verifies that rules produce the correct findings against annotated
source files. Three annotation types are supported:

    ``# expect: rule-id``    — rule MUST fire on this line (TP assertion)
    ``# ok: rule-id``        — rule must NOT fire on this line (FP guard)
    ``# todoruleid: rule-id`` — rule SHOULD fire but is known-missing (not fatal)

Non-Python comments (``//``) are also supported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.filters.pipeline import run_pipeline
from attocode.code_intel.rules.model import EnrichedFinding, UnifiedRule

# ---------------------------------------------------------------------------
# Annotation parsing
# ---------------------------------------------------------------------------

# Matches: # expect: rule-id, // expect: rule-id, # ok: rule-id, etc.
_ANNOTATION_RE = re.compile(
    r"(?:#|//)\s*(expect|ok|todoruleid):\s*([\w./-]+)"
)


@dataclass(slots=True, frozen=True)
class Expectation:
    """A single test annotation from a source file."""

    line: int
    kind: str  # "expect" | "ok" | "todoruleid"
    rule_id: str


def parse_annotations(file_path: str) -> list[Expectation]:
    """Parse all test annotations from a source file."""
    expectations: list[Expectation] = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                for m in _ANNOTATION_RE.finditer(line):
                    expectations.append(Expectation(
                        line=i,
                        kind=m.group(1),
                        rule_id=m.group(2),
                    ))
    except OSError:
        pass  # unreadable file — return empty
    return expectations


# ---------------------------------------------------------------------------
# Test result model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuleTestFileResult:
    """Result of testing rules against a single annotated file."""

    file_path: str
    passed: list[Expectation] = field(default_factory=list)
    failed: list[tuple[Expectation, str]] = field(default_factory=list)
    todoruleid_unexpected_passes: list[Expectation] = field(default_factory=list)
    false_positives: list[tuple[EnrichedFinding, Expectation]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.false_positives

    @property
    def total_assertions(self) -> int:
        return len(self.passed) + len(self.failed) + len(self.false_positives) + len(self.todoruleid_unexpected_passes)


@dataclass(slots=True)
class RuleTestSuiteResult:
    """Aggregated result across multiple test files."""

    file_results: list[RuleTestFileResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.file_results)

    @property
    def total_passed(self) -> int:
        return sum(len(r.passed) for r in self.file_results)

    @property
    def total_failed(self) -> int:
        return sum(len(r.failed) for r in self.file_results)

    @property
    def total_false_positives(self) -> int:
        return sum(len(r.false_positives) for r in self.file_results)

    @property
    def total_todoruleid_passes(self) -> int:
        return sum(len(r.todoruleid_unexpected_passes) for r in self.file_results)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _finding_matches_rule(finding_rule_id: str, expected_rule_id: str) -> bool:
    """Check if a finding's rule_id matches an expected annotation.

    Matching rules (in order):
    1. Exact match: ``"security/eval"`` == ``"security/eval"``
    2. Suffix match: ``"plugin:team/no-print"`` ends with ``"/no-print"``
    """
    if finding_rule_id == expected_rule_id:
        return True
    if finding_rule_id.endswith("/" + expected_rule_id):
        return True
    return False


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


class RuleTestRunner:
    """Run rule tests against annotated fixture files."""

    def __init__(self, rules: list[UnifiedRule], *, project_dir: str = "") -> None:
        self._rules = rules
        self._project_dir = project_dir

    def run_test_file(self, file_path: str) -> RuleTestFileResult:
        """Run rules against a single annotated file and check expectations."""
        result = RuleTestFileResult(file_path=file_path)
        annotations = parse_annotations(file_path)

        if not annotations:
            return result

        # Execute rules
        findings = execute_rules(
            [file_path], self._rules, project_dir=self._project_dir,
        )
        findings = run_pipeline(findings, min_confidence=0.0)

        # Build finding lookup: line -> list of rule_ids
        finding_map: dict[int, list[str]] = {}
        finding_objs: dict[tuple[int, str], EnrichedFinding] = {}
        for f in findings:
            finding_map.setdefault(f.line, []).append(f.rule_id)
            finding_objs[(f.line, f.rule_id)] = f

        for ann in annotations:
            line_findings = finding_map.get(ann.line, [])
            matched = any(
                _finding_matches_rule(fid, ann.rule_id)
                for fid in line_findings
            )

            if ann.kind == "expect":
                if matched:
                    result.passed.append(ann)
                else:
                    result.failed.append((
                        ann,
                        f"Expected '{ann.rule_id}' on line {ann.line} "
                        f"but got {line_findings or 'nothing'}",
                    ))

            elif ann.kind == "ok":
                if matched:
                    # Find the offending finding for the report
                    for fid in line_findings:
                        if _finding_matches_rule(fid, ann.rule_id):
                            obj = finding_objs.get((ann.line, fid))
                            if obj:
                                result.false_positives.append((obj, ann))
                            break
                else:
                    result.passed.append(ann)

            elif ann.kind == "todoruleid":
                if matched:
                    result.todoruleid_unexpected_passes.append(ann)
                # Not matching is expected — not a failure

        return result

    def run_test_suite(self, fixtures_dir: str) -> RuleTestSuiteResult:
        """Run rules against all annotated files in a directory."""
        suite = RuleTestSuiteResult()
        fixtures_path = Path(fixtures_dir)
        if not fixtures_path.is_dir():
            return suite

        for file_path in sorted(fixtures_path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix not in {
                ".py", ".go", ".ts", ".js", ".rs", ".java",
                ".kt", ".rb", ".php", ".swift", ".cs", ".c",
                ".cpp", ".lua", ".sh", ".scala", ".ex",
            }:
                continue
            # Only test files that have annotations
            content = file_path.read_text(encoding="utf-8", errors="replace")
            if not _ANNOTATION_RE.search(content):
                continue

            result = self.run_test_file(str(file_path))
            suite.file_results.append(result)

        return suite


# ---------------------------------------------------------------------------
# Inline test_cases validation (YAML rule self-check)
# ---------------------------------------------------------------------------


def validate_inline_test_cases(
    rule: UnifiedRule,
    test_cases: list[dict],
) -> list[str]:
    """Validate a rule's inline test_cases at load time.

    Each test case: ``{"code": "...", "should_match": true/false}``.
    Returns list of error messages (empty = all passed).
    """
    errors: list[str] = []
    if not rule.pattern:
        return errors

    for i, tc in enumerate(test_cases):
        code = str(tc.get("code", ""))
        should_match = bool(tc.get("should_match", True))
        matched = bool(rule.pattern.search(code))

        if should_match and not matched:
            errors.append(
                f"Rule '{rule.id}' test_case[{i}]: expected match on "
                f"'{code[:60]}' but pattern did not match"
            )
        elif not should_match and matched:
            errors.append(
                f"Rule '{rule.id}' test_case[{i}]: expected no match on "
                f"'{code[:60]}' but pattern matched"
            )

    return errors


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_test_report(suite: RuleTestSuiteResult) -> str:
    """Format a test suite result as markdown."""
    lines: list[str] = []

    status = "PASS" if suite.ok else "FAIL"
    lines.append(f"# Rule Test Report: {status}\n")
    lines.append(
        f"Files: {len(suite.file_results)} | "
        f"Passed: {suite.total_passed} | "
        f"Failed: {suite.total_failed} | "
        f"False Positives: {suite.total_false_positives} | "
        f"Todo Passes: {suite.total_todoruleid_passes}\n"
    )

    for fr in suite.file_results:
        if fr.ok and not fr.todoruleid_unexpected_passes:
            continue  # Only show interesting results

        rel = Path(fr.file_path).name
        lines.append(f"## {rel}\n")

        if fr.failed:
            lines.append("### Missing Expected Findings\n")
            for exp, reason in fr.failed:
                lines.append(f"- Line {exp.line}: `{exp.rule_id}` — {reason}")
            lines.append("")

        if fr.false_positives:
            lines.append("### False Positives (# ok: violations)\n")
            for finding, ann in fr.false_positives:
                lines.append(
                    f"- Line {ann.line}: `{ann.rule_id}` fired but was marked `# ok:` "
                    f"({finding.code_snippet[:60]})"
                )
            lines.append("")

        if fr.todoruleid_unexpected_passes:
            lines.append("### Unexpected Passes (todoruleid now matching!)\n")
            for exp in fr.todoruleid_unexpected_passes:
                lines.append(
                    f"- Line {exp.line}: `{exp.rule_id}` — "
                    f"previously known-missing, now matching! Consider upgrading to `# expect:`"
                )
            lines.append("")

    return "\n".join(lines)
