"""Security compliance scanner.

Scans source files for secrets, anti-patterns, and dependency issues.
All scanning is local — no external API calls for basic mode.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from attocode.integrations.security.patterns import (
    ANTI_PATTERNS,
    SECRET_PATTERNS,
    Category,
    SecurityPattern,
    Severity,
)

logger = logging.getLogger(__name__)

# Extensions worth scanning (source code, not binary/media)
_SCANNABLE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".rs", ".go", ".java", ".kt", ".rb", ".php", ".swift", ".cs",
    ".c", ".cpp", ".h", ".hpp", ".lua", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json", ".env", ".cfg", ".ini", ".conf",
}

# Dot-files that should still be scanned (e.g. .env contains secrets)
_SCANNABLE_DOTFILES = {".env", ".envrc", ".env.local", ".env.production", ".env.staging"}
_EXTRA_IGNORED_DIRS = {"site"}
_PATTERN_DEFINITION_FILES = {
    os.path.normpath("src/attocode/integrations/security/patterns.py"),
}


@dataclass(slots=True)
class SecurityFinding:
    """A single security finding."""

    severity: Severity
    category: Category
    file_path: str
    line: int
    message: str
    recommendation: str
    cwe_id: str = ""
    pattern_name: str = ""


@dataclass(slots=True)
class SecurityReport:
    """Full security scan report."""

    findings: list[SecurityFinding]
    scan_time_ms: float
    files_scanned: int
    summary: dict[str, int] = field(default_factory=dict)  # severity -> count
    compliance_score: int = 100


@dataclass(slots=True)
class SecurityScanner:
    """Scan a project for security issues.

    Three scan modes:
    - ``quick``: secrets only, fast
    - ``full``: secrets + anti-patterns + dependencies
    - ``secrets``: only secret detection
    - ``patterns``: only code anti-patterns
    - ``dependencies``: only dependency audit
    """

    root_dir: str
    _language_map: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        from attocode.integrations.context.codebase_context import EXTENSION_LANGUAGES
        self._language_map = dict(EXTENSION_LANGUAGES)

    def scan(
        self,
        mode: str = "full",
        path: str = "",
    ) -> SecurityReport:
        """Run a security scan.

        Args:
            mode: Scan mode — 'quick', 'full', 'secrets', 'patterns', 'dependencies'.
            path: Optional subdirectory to scan (relative to root).

        Returns:
            SecurityReport with findings and compliance score.
        """
        start = time.monotonic()
        findings: list[SecurityFinding] = []
        files_scanned = 0

        # Resolve and validate path stays inside root_dir to prevent traversal
        if path:
            resolved = (Path(self.root_dir) / path).resolve()
            root_resolved = Path(self.root_dir).resolve()
            if not str(resolved).startswith(str(root_resolved) + os.sep) and resolved != root_resolved:
                return SecurityReport(findings=[], scan_time_ms=0, files_scanned=0, summary={}, compliance_score=100)
            scan_root = str(resolved)
        else:
            scan_root = self.root_dir

        run_secrets = mode in ("quick", "full", "secrets")
        run_patterns = mode in ("full", "patterns")
        run_deps = mode in ("full", "dependencies")

        if run_secrets or run_patterns:
            files_scanned, file_findings = self._scan_files(
                scan_root, run_secrets=run_secrets, run_patterns=run_patterns,
            )
            findings.extend(file_findings)

        if run_deps:
            from attocode.integrations.security.dependency_audit import DependencyAuditor
            auditor = DependencyAuditor(root_dir=self.root_dir)
            dep_findings = auditor.audit()
            for df in dep_findings:
                findings.append(SecurityFinding(
                    severity=df.severity,
                    category=df.category,
                    file_path=df.source_file,
                    line=0,
                    message=df.message,
                    recommendation=df.recommendation,
                    cwe_id=df.cwe_id,
                    pattern_name=df.package,
                ))

        # Compute summary
        summary: dict[str, int] = {}
        for f in findings:
            summary[f.severity] = summary.get(f.severity, 0) + 1

        # Compute compliance score
        score = self._compute_score(summary)

        elapsed = (time.monotonic() - start) * 1000

        return SecurityReport(
            findings=findings,
            scan_time_ms=round(elapsed, 1),
            files_scanned=files_scanned,
            summary=summary,
            compliance_score=score,
        )

    def _scan_files(
        self,
        scan_root: str,
        *,
        run_secrets: bool = True,
        run_patterns: bool = True,
    ) -> tuple[int, list[SecurityFinding]]:
        """Scan all source files for secrets and/or anti-patterns."""
        findings: list[SecurityFinding] = []
        files_scanned = 0

        from attocode.integrations.context.codebase_context import (
            DEFAULT_IGNORES,
            SKIP_EXTENSIONS,
            SKIP_FILENAMES,
        )

        for dirpath, dirnames, filenames in os.walk(scan_root):
            rel_dir = os.path.relpath(dirpath, self.root_dir)
            rel_parts = set(Path(rel_dir).parts) if rel_dir not in (".", "") else set()
            # Filter ignored directories
            dirnames[:] = [
                d for d in dirnames
                if d not in DEFAULT_IGNORES
                and d not in _EXTRA_IGNORED_DIRS
                and d not in rel_parts
                and not d.startswith(".")
            ]

            for filename in filenames:
                if filename.startswith(".") and filename not in _SCANNABLE_DOTFILES:
                    continue
                if filename in SKIP_FILENAMES:
                    continue
                ext = Path(filename).suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue
                if ext not in _SCANNABLE_EXTENSIONS:
                    continue

                full_path = os.path.join(dirpath, filename)
                try:
                    rel_path = os.path.relpath(full_path, self.root_dir)
                except ValueError:
                    continue
                rel_path_norm = os.path.normpath(rel_path)

                if rel_path_norm in _PATTERN_DEFINITION_FILES:
                    continue

                try:
                    content = Path(full_path).read_text(
                        encoding="utf-8", errors="replace",
                    )
                except OSError:
                    continue

                files_scanned += 1
                language = self._language_map.get(ext, "")

                if run_secrets:
                    findings.extend(
                        self._scan_content(content, rel_path, SECRET_PATTERNS, language),
                    )

                if run_patterns:
                    findings.extend(
                        self._scan_content(content, rel_path, ANTI_PATTERNS, language),
                    )

        return files_scanned, findings

    def _scan_content(
        self,
        content: str,
        file_path: str,
        patterns: list[SecurityPattern],
        language: str,
    ) -> list[SecurityFinding]:
        """Scan file content against a set of patterns."""
        findings: list[SecurityFinding] = []

        for pat in patterns:
            # Skip language-specific patterns that don't apply
            if pat.languages and language not in pat.languages:
                continue

            for i, line in enumerate(content.split("\n"), 1):
                # Skip comment lines (basic heuristic)
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue

                if pat.pattern.search(line):
                    findings.append(SecurityFinding(
                        severity=pat.severity,
                        category=pat.category,
                        file_path=file_path,
                        line=i,
                        message=pat.message,
                        recommendation=pat.recommendation,
                        cwe_id=pat.cwe_id,
                        pattern_name=pat.name,
                    ))

        return findings

    @staticmethod
    def _compute_score(summary: dict[str, int]) -> int:
        """Compute compliance score (0-100).

        score = 100 - (critical * 20 + high * 10 + medium * 3 + low * 1)
        """
        deductions = (
            summary.get("critical", 0) * 20
            + summary.get("high", 0) * 10
            + summary.get("medium", 0) * 3
            + summary.get("low", 0) * 1
        )
        return max(0, min(100, 100 - deductions))

    def format_report(self, report: SecurityReport) -> str:
        """Format a SecurityReport as human-readable text."""
        lines: list[str] = []

        # Header
        lines.append("Security Scan Report")
        lines.append(f"Score: {report.compliance_score}/100 | "
                      f"Files: {report.files_scanned} | "
                      f"Time: {report.scan_time_ms:.0f}ms")
        lines.append("")

        # Summary
        if report.summary:
            parts = []
            for sev in ("critical", "high", "medium", "low", "info"):
                count = report.summary.get(sev, 0)
                if count > 0:
                    parts.append(f"{sev}: {count}")
            lines.append(f"Findings: {' | '.join(parts)}")
            lines.append("")

        if not report.findings:
            lines.append("No security issues found.")
            return "\n".join(lines)

        # Group findings by severity
        by_severity: dict[str, list[SecurityFinding]] = {}
        for f in report.findings:
            by_severity.setdefault(f.severity, []).append(f)

        for sev in ("critical", "high", "medium", "low", "info"):
            group = by_severity.get(sev, [])
            if not group:
                continue
            lines.append(f"## {sev.upper()} ({len(group)})")
            for f in group[:20]:  # Cap per-severity to avoid huge output
                cwe = f" [{f.cwe_id}]" if f.cwe_id else ""
                lines.append(f"  {f.file_path}:{f.line}{cwe}")
                lines.append(f"    {f.message}")
                lines.append(f"    → {f.recommendation}")
            if len(group) > 20:
                lines.append(f"  ... and {len(group) - 20} more {sev} findings")
            lines.append("")

        return "\n".join(lines)
