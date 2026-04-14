"""CI-enforceable rule runner.

Provides a synchronous, exit-code-driven interface for running rules
in CI/CD pipelines. Supports diff-only scanning, SARIF output, and
GitHub Actions annotations.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.model import EnrichedFinding, RuleSeverity

logger = logging.getLogger(__name__)

# Severity ordering for threshold comparison
_SEV_ORDER = {
    RuleSeverity.CRITICAL: 0,
    RuleSeverity.HIGH: 1,
    RuleSeverity.MEDIUM: 2,
    RuleSeverity.LOW: 3,
    RuleSeverity.INFO: 4,
}


@dataclass(slots=True)
class CIResult:
    """Result of a CI scan run."""

    findings: list[EnrichedFinding]
    exit_code: int = 0
    files_scanned: int = 0
    rules_applied: int = 0
    findings_above_threshold: int = 0

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(slots=True)
class CIConfig:
    """Configuration for CI scans, loadable from .attocode/ci.yaml."""

    fail_on: RuleSeverity = RuleSeverity.HIGH
    baseline: str = ""  # git ref for diff-only
    exclude_rules: list[str] = field(default_factory=list)
    sarif_output: str = ""  # path to write SARIF
    min_confidence: float = 0.5
    max_findings: int = 200


def load_ci_config(project_dir: str) -> CIConfig:
    """Load CI config from .attocode/ci.yaml if it exists."""
    config_path = Path(project_dir) / ".attocode" / "ci.yaml"
    if not config_path.is_file():
        return CIConfig()

    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return CIConfig()

        cfg = CIConfig()
        if "fail_on" in data:
            sev = str(data["fail_on"]).lower()
            if sev in {s.value for s in RuleSeverity}:
                cfg.fail_on = RuleSeverity(sev)
        cfg.baseline = str(data.get("baseline", ""))
        cfg.exclude_rules = list(data.get("exclude_rules", []))
        cfg.sarif_output = str(data.get("sarif_output", ""))
        cfg.min_confidence = float(data.get("min_confidence", 0.5))
        cfg.max_findings = int(data.get("max_findings", 200))
        return cfg
    except Exception as exc:
        logger.warning("Failed to load CI config: %s", exc)
        return CIConfig()


def get_changed_files(
    base_ref: str,
    project_dir: str,
) -> list[str]:
    """Get files changed since *base_ref* using git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            capture_output=True, text=True, cwd=project_dir,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("git diff failed: %s", result.stderr.strip())
            return []

        files = []
        for line in result.stdout.strip().splitlines():
            abs_path = os.path.join(project_dir, line)
            if os.path.isfile(abs_path):
                files.append(abs_path)
        return files
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to get changed files: %s", exc)
        return []


def get_changed_lines(
    base_ref: str,
    file_path: str,
    project_dir: str,
) -> set[int]:
    """Get line numbers that changed in *file_path* since *base_ref*."""
    try:
        rel_path = os.path.relpath(file_path, project_dir)
        result = subprocess.run(
            ["git", "diff", "-U0", base_ref, "--", rel_path],
            capture_output=True, text=True, cwd=project_dir,
            timeout=30,
        )
        if result.returncode != 0:
            return set()

        import re as _re
        _HUNK_RE = _re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

        changed: set[int] = set()
        for line in result.stdout.splitlines():
            m = _HUNK_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                changed.update(range(start, start + count))
        return changed
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return set()


class CIRunner:
    """Run rules in CI mode with exit codes and structured output."""

    def __init__(self, project_dir: str, config: CIConfig | None = None) -> None:
        self.project_dir = project_dir
        self.config = config or load_ci_config(project_dir)

    def run(
        self,
        files: list[str] | None = None,
        path: str = "",
        language: str = "",
        category: str = "",
        *,
        diff_only: bool = False,
    ) -> CIResult:
        """Execute rules in CI mode.

        Args:
            files: Explicit file list to scan.
            path: Directory to scan (relative to project root).
            language: Filter rules to this language.
            category: Filter by category.
            diff_only: Only report findings on changed lines since baseline.

        Returns:
            CIResult with findings and exit code.
        """
        from attocode.code_intel.rules.registry import RuleRegistry
        from attocode.code_intel.rules.loader import load_builtin_rules, load_user_rules
        from attocode.code_intel.rules.packs.pack_loader import load_all_packs
        from attocode.code_intel.rules.executor import execute_rules
        from attocode.code_intel.rules.enricher import enrich_findings
        from attocode.code_intel.rules.filters.pipeline import run_pipeline

        # Build registry
        reg = RuleRegistry()
        reg.register_many(load_builtin_rules())
        pack_manifests, pack_rules = load_all_packs(self.project_dir)
        reg.register_many(pack_rules)
        user_rules = load_user_rules(self.project_dir)
        reg.register_many(user_rules)

        # Query applicable rules
        rules = reg.query(
            language=language,
            category=category,
            min_confidence=self.config.min_confidence,
        )

        # Exclude rules from config
        if self.config.exclude_rules:
            exclude = set(self.config.exclude_rules)
            rules = [r for r in rules if r.qualified_id not in exclude and r.id not in exclude]

        # Collect files
        if diff_only and self.config.baseline:
            file_list = files or get_changed_files(self.config.baseline, self.project_dir)
        else:
            from attocode.code_intel.tools.rule_tools import _collect_files
            file_list = _collect_files(files, path, self.project_dir)

        if not file_list or not rules:
            return CIResult(findings=[], files_scanned=len(file_list or []), rules_applied=len(rules))

        # Execute
        findings = execute_rules(file_list, rules, project_dir=self.project_dir)
        findings = run_pipeline(findings, min_confidence=self.config.min_confidence)
        enrich_findings(findings, project_dir=self.project_dir)

        # Diff-only filtering: only keep findings on changed lines
        if diff_only and self.config.baseline:
            changed_lines_cache: dict[str, set[int]] = {}
            filtered = []
            for f in findings:
                abs_path = f.file if os.path.isabs(f.file) else os.path.join(self.project_dir, f.file)
                if abs_path not in changed_lines_cache:
                    changed_lines_cache[abs_path] = get_changed_lines(
                        self.config.baseline, abs_path, self.project_dir,
                    )
                if f.line in changed_lines_cache[abs_path]:
                    filtered.append(f)
            findings = filtered

        # Cap findings
        findings = findings[:self.config.max_findings]

        # Compute exit code based on threshold
        threshold = _SEV_ORDER.get(self.config.fail_on, 1)
        above = [f for f in findings if _SEV_ORDER.get(RuleSeverity(f.severity), 4) <= threshold]

        result = CIResult(
            findings=findings,
            exit_code=1 if above else 0,
            files_scanned=len(file_list),
            rules_applied=len(rules),
            findings_above_threshold=len(above),
        )

        # Write SARIF if configured
        if self.config.sarif_output:
            self._write_sarif(findings)

        return result

    def _write_sarif(self, findings: list[EnrichedFinding]) -> None:
        """Write findings as SARIF to the configured output path."""
        from attocode.code_intel.rules.sarif import findings_to_sarif, sarif_to_json

        sarif = findings_to_sarif(findings)
        output_path = Path(self.config.sarif_output)
        if not output_path.is_absolute():
            output_path = Path(self.project_dir) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(sarif_to_json(sarif), encoding="utf-8")
        logger.info("SARIF output written to %s", output_path)


def format_github_annotations(findings: list[EnrichedFinding]) -> str:
    """Format findings as GitHub Actions annotation commands.

    Output format: ``::error file=path,line=N::message``
    """
    _LEVEL = {
        RuleSeverity.CRITICAL: "error",
        RuleSeverity.HIGH: "error",
        RuleSeverity.MEDIUM: "warning",
        RuleSeverity.LOW: "notice",
        RuleSeverity.INFO: "notice",
    }
    lines: list[str] = []
    for f in findings:
        level = _LEVEL.get(RuleSeverity(f.severity), "warning")
        msg = f"[{f.rule_id}] {f.description}"
        # GitHub Actions requires percent-encoding for %, \r, \n in messages
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        lines.append(f"::{level} file={f.file},line={f.line}::{msg}")
    return "\n".join(lines)


def format_ci_summary(result: CIResult) -> str:
    """Format a CI result as a human-readable summary."""
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"## Rule Analysis: {status}",
        f"Files scanned: {result.files_scanned} | Rules applied: {result.rules_applied}",
        f"Findings: {len(result.findings)} total, {result.findings_above_threshold} above threshold",
    ]

    if result.findings:
        # Group by severity
        by_sev: dict[str, int] = {}
        for f in result.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        lines.append("Breakdown: " + ", ".join(f"{s}: {c}" for s, c in sorted(by_sev.items())))

        # Top findings
        lines.append("")
        for f in result.findings[:10]:
            lines.append(f"- [{f.severity}] {f.file}:{f.line} — {f.description[:80]}")
        if len(result.findings) > 10:
            lines.append(f"... and {len(result.findings) - 10} more")

    return "\n".join(lines)
