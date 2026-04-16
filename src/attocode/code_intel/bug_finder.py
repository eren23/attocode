"""Bug finder — scans diffs for potential issues.

Analyzes code changes between branches, looking for common
bug patterns, edge cases, security issues, and performance
problems. Reports findings with confidence levels.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

from attocode.types.severity import Severity

logger = logging.getLogger(__name__)


class FindingCategory(StrEnum):
    """Category of bug finding."""
    LOGIC_ERROR = "logic_error"
    EDGE_CASE = "edge_case"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ERROR_HANDLING = "error_handling"
    TYPE_SAFETY = "type_safety"
    CONCURRENCY = "concurrency"
    RESOURCE_LEAK = "resource_leak"


@dataclass(slots=True)
class Finding:
    """A single bug finding."""
    file: str
    line: int
    severity: Severity
    category: FindingCategory
    confidence: float  # 0.0-1.0
    description: str
    suggestion: str = ""
    code_snippet: str = ""


@dataclass(slots=True)
class BugReport:
    """Complete bug report for a scan."""
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    lines_analyzed: int = 0
    scan_duration: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    def filter_by_confidence(self, min_confidence: float = 0.5) -> list[Finding]:
        """Filter findings by minimum confidence level."""
        return [f for f in self.findings if f.confidence >= min_confidence]

    def format_report(self, *, min_confidence: float = 0.5) -> str:
        """Format findings as a human-readable report."""
        filtered = self.filter_by_confidence(min_confidence)
        if not filtered:
            return f"No findings above {min_confidence:.0%} confidence ({self.files_scanned} files scanned)."

        lines = [
            f"Bug Report: {len(filtered)} findings ({self.files_scanned} files, {self.lines_analyzed} lines)",
            "",
        ]

        # Group by severity
        for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
            group = [f for f in filtered if f.severity == severity]
            if not group:
                continue
            lines.append(f"### {severity.value.upper()} ({len(group)})")
            for finding in group:
                confidence_pct = f"{finding.confidence:.0%}"
                lines.append(
                    f"  [{confidence_pct}] {finding.file}:{finding.line} — "
                    f"{finding.description}"
                )
                if finding.suggestion:
                    lines.append(f"         Fix: {finding.suggestion}")
            lines.append("")

        return "\n".join(lines)


# --- Static pattern-based analysis ---

_PATTERNS: list[tuple[str, FindingCategory, Severity, str, float]] = [
    # (regex, category, severity, description_template, confidence)
    (r"except\s*:", FindingCategory.ERROR_HANDLING, Severity.MEDIUM,
     "Bare except clause catches all exceptions including KeyboardInterrupt", 0.9),
    (r"eval\s*\(", FindingCategory.SECURITY, Severity.HIGH,
     "Use of eval() can execute arbitrary code", 0.85),
    (r"exec\s*\(", FindingCategory.SECURITY, Severity.HIGH,
     "Use of exec() can execute arbitrary code", 0.8),
    (r"subprocess\.call\(.*shell\s*=\s*True", FindingCategory.SECURITY, Severity.HIGH,
     "subprocess with shell=True is vulnerable to injection", 0.85),
    (r"\.format\(.*\)\s*$", FindingCategory.SECURITY, Severity.LOW,
     "Consider f-strings over .format() for clarity", 0.3),
    (r"TODO|FIXME|HACK|XXX", FindingCategory.LOGIC_ERROR, Severity.INFO,
     "Unresolved TODO/FIXME marker", 0.95),
    (r"time\.sleep\(\d{2,}", FindingCategory.PERFORMANCE, Severity.MEDIUM,
     "Long sleep duration may indicate polling pattern", 0.6),
    (r"except\s+Exception\s+as\s+\w+:\s*\n\s*pass", FindingCategory.ERROR_HANDLING, Severity.MEDIUM,
     "Exception silently swallowed", 0.75),
]


def scan_text(
    text: str,
    file_path: str = "<unknown>",
    *,
    line_offset: int = 0,
) -> list[Finding]:
    """Scan text for common bug patterns.

    Args:
        text: Source code text.
        file_path: File path for reporting.
        line_offset: Line offset for diff-based scanning.

    Returns:
        List of findings.
    """
    findings: list[Finding] = []
    lines = text.split("\n")

    for i, line in enumerate(lines, start=1 + line_offset):
        for pattern, category, severity, desc, confidence in _PATTERNS:
            if re.search(pattern, line):
                findings.append(Finding(
                    file=file_path,
                    line=i,
                    severity=severity,
                    category=category,
                    confidence=confidence,
                    description=desc,
                    code_snippet=line.strip()[:120],
                ))

    return findings


def parse_diff_files(diff_text: str) -> list[tuple[str, str]]:
    """Parse a unified diff into (file_path, changed_content) pairs."""
    files: list[tuple[str, str]] = []
    current_file = ""
    current_lines: list[str] = []

    for line in diff_text.split("\n"):
        if line.startswith("+++ b/"):
            if current_file and current_lines:
                files.append((current_file, "\n".join(current_lines)))
            current_file = line[6:]
            current_lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            current_lines.append(line[1:])  # Strip the leading +

    if current_file and current_lines:
        files.append((current_file, "\n".join(current_lines)))

    return files


def scan_diff(diff_text: str) -> BugReport:
    """Scan a unified diff for bug patterns.

    Parses the diff, extracts added lines, and runs
    pattern-based analysis on each changed file.
    """
    files = parse_diff_files(diff_text)
    all_findings: list[Finding] = []
    total_lines = 0

    for file_path, content in files:
        if not file_path.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")):
            continue
        findings = scan_text(content, file_path)
        all_findings.extend(findings)
        total_lines += content.count("\n") + 1

    return BugReport(
        findings=all_findings,
        files_scanned=len(files),
        lines_analyzed=total_lines,
    )
