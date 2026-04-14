"""Golden tests for rule violations — verifies rules catch what they should.

Each fixture file in tests/fixtures/rule_violations/ contains intentional
violations annotated with `# expect: <rule-id>` (or `// expect: <rule-id>`
for non-Python languages). The test runner:

1. Loads all rules (builtin + packs + the fixture's custom .attocode/rules/)
2. Executes rules against each fixture file
3. Parses expect annotations from the file
4. Verifies every expected rule fires on the annotated line
5. Flags unexpected findings as test failures (false positives)

This ensures rules work as documented and custom team preferences
are enforced alongside builtin checks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from attocode.code_intel.rules.registry import RuleRegistry
from attocode.code_intel.rules.loader import load_builtin_rules, load_yaml_rules, load_user_rules
from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack
from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.filters.pipeline import run_pipeline
from attocode.code_intel.rules.model import RuleSource

# ---------------------------------------------------------------------------
# Annotation parser — delegates to the shared testing module
# ---------------------------------------------------------------------------

from attocode.code_intel.rules.testing import (
    Expectation,
    parse_annotations,
    _finding_matches_rule,
)


def parse_expectations(file_path: str) -> list[Expectation]:
    """Parse # expect: rule-id annotations from a source file.

    Now delegates to the shared testing module which also handles
    ``# ok:`` and ``# todoruleid:`` annotations.
    """
    return [
        a for a in parse_annotations(file_path)
        if a.kind == "expect"
    ]


# ---------------------------------------------------------------------------
# Fixture setup
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "rule_violations"


@pytest.fixture(scope="module")
def full_registry() -> RuleRegistry:
    """Build a registry with builtins + example packs + fixture custom rules."""
    reg = RuleRegistry()

    builtins = load_builtin_rules()
    reg.register_many(builtins)

    # Load ALL example packs for testing (in real use, users install selectively)
    for manifest in list_example_packs():
        reg.register_many(load_pack(manifest))

    # Load the fixture's custom team rules
    custom = load_user_rules(str(FIXTURES_DIR))
    reg.register_many(custom)

    return reg


# ---------------------------------------------------------------------------
# Per-language test cases
# ---------------------------------------------------------------------------

_TEST_FILES = [
    ("python/bad_patterns.py", "python"),
    ("go/bad_patterns.go", "go"),
    ("typescript/bad_patterns.ts", "typescript"),
    ("rust/bad_patterns.rs", "rust"),
    ("java/BadPatterns.java", "java"),
]


@pytest.mark.parametrize("rel_path,language", _TEST_FILES, ids=[t[1] for t in _TEST_FILES])
def test_expected_violations_caught(
    full_registry: RuleRegistry,
    rel_path: str,
    language: str,
) -> None:
    """Verify every # expect annotation produces a finding."""
    file_path = str(FIXTURES_DIR / rel_path)
    if not os.path.isfile(file_path):
        pytest.skip(f"Fixture not found: {file_path}")

    expectations = parse_expectations(file_path)
    assert expectations, f"No expect annotations in {rel_path} — add some or remove from test list"

    # Run rules
    rules = full_registry.query(language=language, min_confidence=0.0)
    # Also include universal rules
    universal = full_registry.query(min_confidence=0.0)
    seen_ids = set()
    combined = []
    for r in rules + universal:
        if r.qualified_id not in seen_ids:
            combined.append(r)
            seen_ids.add(r.qualified_id)

    findings = execute_rules([file_path], combined, project_dir=str(FIXTURES_DIR))
    findings = run_pipeline(findings, min_confidence=0.0)

    # Build a lookup: (line, rule_id) -> finding
    finding_map: dict[int, list[str]] = {}
    for f in findings:
        finding_map.setdefault(f.line, []).append(f.rule_id)

    # Check each expectation
    missed: list[str] = []
    for exp in expectations:
        line_findings = finding_map.get(exp.line, [])
        matched = any(
            _finding_matches_rule(fid, exp.rule_id)
            for fid in line_findings
        )
        if not matched:
            missed.append(
                f"  Line {exp.line}: expected '{exp.rule_id}' but got {line_findings or 'nothing'}"
            )

    if missed:
        pytest.fail(
            f"Missing expected violations in {rel_path}:\n" + "\n".join(missed)
        )


@pytest.mark.parametrize("rel_path,language", _TEST_FILES, ids=[t[1] for t in _TEST_FILES])
def test_clean_functions_produce_no_findings(
    full_registry: RuleRegistry,
    rel_path: str,
    language: str,
) -> None:
    """Verify lines without # expect annotations don't produce findings.

    This catches false positives. We only check non-annotated code lines
    that are inside functions named 'clean*' or 'Clean*' to avoid being
    too strict about incidental matches on imports/comments.
    """
    file_path = str(FIXTURES_DIR / rel_path)
    if not os.path.isfile(file_path):
        pytest.skip(f"Fixture not found: {file_path}")

    expectations = parse_expectations(file_path)
    expected_lines = {e.line for e in expectations}

    # Find "clean function" line ranges
    lines = Path(file_path).read_text(encoding="utf-8").splitlines()
    clean_ranges: list[tuple[int, int]] = []
    _clean_fn_re = re.compile(
        r"(?:def\s+clean|func\s+[Cc]lean|function\s+clean|fn\s+clean|"
        r"(?:public|private)\s+\w+\s+clean)\w*\("
    )
    for i, line in enumerate(lines, 1):
        if _clean_fn_re.search(line):
            # Find end (next function or end of file)
            end = len(lines)
            for j in range(i, len(lines)):
                if j > i and _clean_fn_re.search(lines[j]):
                    end = j
                    break
            clean_ranges.append((i, end))

    if not clean_ranges:
        pytest.skip(f"No clean* functions in {rel_path}")

    # Run rules
    rules = full_registry.query(language=language, min_confidence=0.0)
    universal = full_registry.query(min_confidence=0.0)
    seen_ids = set()
    combined = []
    for r in rules + universal:
        if r.qualified_id not in seen_ids:
            combined.append(r)
            seen_ids.add(r.qualified_id)

    findings = execute_rules([file_path], combined, project_dir=str(FIXTURES_DIR))
    findings = run_pipeline(findings, min_confidence=0.3)

    # Check for false positives in clean function ranges
    false_positives: list[str] = []
    for f in findings:
        if f.line in expected_lines:
            continue  # annotated, skip
        for start, end in clean_ranges:
            if start <= f.line <= end:
                false_positives.append(
                    f"  Line {f.line}: unexpected '{f.rule_id}' in clean function ({f.code_snippet[:60]})"
                )

    if false_positives:
        pytest.fail(
            f"False positives in clean functions of {rel_path}:\n" + "\n".join(false_positives)
        )


# ---------------------------------------------------------------------------
# # ok: annotation tests — verify FP guards work
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel_path,language", _TEST_FILES, ids=[t[1] for t in _TEST_FILES])
def test_ok_annotations_not_matched(
    full_registry: RuleRegistry,
    rel_path: str,
    language: str,
) -> None:
    """Verify lines annotated with # ok: rule-id do NOT produce that finding."""
    file_path = str(FIXTURES_DIR / rel_path)
    if not os.path.isfile(file_path):
        pytest.skip(f"Fixture not found: {file_path}")

    ok_annotations = [
        a for a in parse_annotations(file_path) if a.kind == "ok"
    ]
    if not ok_annotations:
        pytest.skip(f"No # ok: annotations in {rel_path}")

    # Run rules
    rules = full_registry.query(language=language, min_confidence=0.0)
    universal = full_registry.query(min_confidence=0.0)
    seen_ids = set()
    combined = []
    for r in rules + universal:
        if r.qualified_id not in seen_ids:
            combined.append(r)
            seen_ids.add(r.qualified_id)

    findings = execute_rules([file_path], combined, project_dir=str(FIXTURES_DIR))
    findings = run_pipeline(findings, min_confidence=0.0)

    finding_map: dict[int, list[str]] = {}
    for f in findings:
        finding_map.setdefault(f.line, []).append(f.rule_id)

    violations: list[str] = []
    for ann in ok_annotations:
        line_findings = finding_map.get(ann.line, [])
        matched = any(
            _finding_matches_rule(fid, ann.rule_id)
            for fid in line_findings
        )
        if matched:
            violations.append(
                f"  Line {ann.line}: rule '{ann.rule_id}' fired but was marked # ok:"
            )

    if violations:
        pytest.fail(
            f"False positives in {rel_path} (# ok: violations):\n" + "\n".join(violations)
        )
