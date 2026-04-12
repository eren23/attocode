"""Pre-filter pipeline — orchestrates deterministic finding filters.

Reduces noise before the connected coding agent sees findings:
1. Dedup — remove exact duplicates and merge overlapping findings
2. Dead code filter — skip findings in unreferenced functions
3. Test file adjuster — lower severity for test/spec files
4. Confidence threshold — drop findings below minimum confidence

No LLM in this pipeline. These are all mechanical, deterministic filters.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict

from attocode.code_intel.rules.model import EnrichedFinding, RuleSeverity

logger = logging.getLogger(__name__)

# Test file patterns
_TEST_FILE_PATTERNS = [
    re.compile(r"test[_/]"),
    re.compile(r"_test\.\w+$"),
    re.compile(r"\.test\.\w+$"),
    re.compile(r"\.spec\.\w+$"),
    re.compile(r"__tests__/"),
    re.compile(r"tests?/"),
    re.compile(r"conftest\.py$"),
    re.compile(r"fixtures?/"),
]


def _is_test_file(file_path: str) -> bool:
    normalized = file_path.replace(os.sep, "/")
    return any(p.search(normalized) for p in _TEST_FILE_PATTERNS)


# Severity demotion map for test files
_SEVERITY_DEMOTION = {
    RuleSeverity.CRITICAL: RuleSeverity.HIGH,
    RuleSeverity.HIGH: RuleSeverity.MEDIUM,
    RuleSeverity.MEDIUM: RuleSeverity.LOW,
    RuleSeverity.LOW: RuleSeverity.INFO,
}


def dedup_findings(findings: list[EnrichedFinding]) -> list[EnrichedFinding]:
    """Remove exact duplicates and merge overlapping findings.

    Two findings overlap if they're on the same file:line with the same
    category. Keep the one with higher confidence.
    """
    seen: dict[tuple[str, int, str], EnrichedFinding] = {}
    for f in findings:
        key = (f.file, f.line, str(f.category))
        existing = seen.get(key)
        if existing is None or f.confidence >= existing.confidence:
            if existing is not None and existing.rule_id != f.rule_id:
                f.related_findings = list(set(f.related_findings + [existing.rule_id]))
            seen[key] = f
        elif existing.rule_id != f.rule_id:
            # f lost the confidence race — record its existence on the winner
            existing.related_findings = list(set(existing.related_findings + [f.rule_id]))

    return list(seen.values())


def adjust_test_file_severity(
    findings: list[EnrichedFinding],
) -> list[EnrichedFinding]:
    """Lower severity for findings in test files."""
    for f in findings:
        if _is_test_file(f.file):
            new_sev = _SEVERITY_DEMOTION.get(f.severity)
            if new_sev:
                f.severity = new_sev
                f.confidence *= 0.8  # reduce confidence for test files
    return findings


def filter_by_confidence(
    findings: list[EnrichedFinding],
    min_confidence: float = 0.5,
) -> list[EnrichedFinding]:
    """Drop findings below confidence threshold."""
    return [f for f in findings if f.confidence >= min_confidence]


def run_pipeline(
    findings: list[EnrichedFinding],
    *,
    min_confidence: float = 0.5,
    adjust_test_severity: bool = True,
) -> list[EnrichedFinding]:
    """Run the full deterministic pre-filter pipeline.

    Pipeline stages:
    1. Dedup overlapping findings
    2. Adjust severity for test files
    3. Apply confidence threshold

    Args:
        findings: Raw findings from executor.
        min_confidence: Minimum confidence to keep (default 0.5).
        adjust_test_severity: Whether to demote test file severity.

    Returns:
        Filtered findings ready for the agent.
    """
    original_count = len(findings)

    # 1. Dedup
    findings = dedup_findings(findings)
    dedup_removed = original_count - len(findings)

    # 2. Test file severity adjustment
    if adjust_test_severity:
        findings = adjust_test_file_severity(findings)

    # 3. Confidence threshold
    findings = filter_by_confidence(findings, min_confidence)
    conf_removed = original_count - dedup_removed - len(findings)

    if dedup_removed > 0 or conf_removed > 0:
        logger.info(
            "Pre-filter: %d → %d findings (-%d dedup, -%d low-confidence)",
            original_count, len(findings), dedup_removed, max(0, conf_removed),
        )

    # Re-sort after filtering
    _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (_sev_order.get(f.severity, 9), f.file, f.line))

    return findings
