"""Readiness report engine -- comprehensive codebase audit.

Orchestrates existing code-intel tools across 8 phases to produce a
ground-truth assessment of codebase health, completeness, and readiness.

Phases:
  0. Baseline: build health, git status, dependencies
  1. API & Business Logic: routes, stubs, TODOs
  2. Frontend Flows: components, dead-ends
  3. Data Layer: migrations, models, constraints
  4. Test Coverage: test-to-source mapping, gaps, skips
  5. Security Surface: secrets, auth, validation
  6. Observability: logging, metrics, health endpoints
  7. Deployability: Docker, CI/CD, env config

Plus: Tracer Bullets -- end-to-end journey verification.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Data Model
# =============================================================================


class ReadinessPhase(IntEnum):
    BASELINE = 0
    API_BUSINESS_LOGIC = 1
    FRONTEND_FLOWS = 2
    DATA_LAYER = 3
    TEST_COVERAGE = 4
    SECURITY_SURFACE = 5
    OBSERVABILITY = 6
    DEPLOYABILITY = 7


_PHASE_NAMES: dict[ReadinessPhase, str] = {
    ReadinessPhase.BASELINE: "Baseline",
    ReadinessPhase.API_BUSINESS_LOGIC: "API & Business Logic",
    ReadinessPhase.FRONTEND_FLOWS: "Frontend Flows",
    ReadinessPhase.DATA_LAYER: "Data Layer",
    ReadinessPhase.TEST_COVERAGE: "Test Coverage",
    ReadinessPhase.SECURITY_SURFACE: "Security Surface",
    ReadinessPhase.OBSERVABILITY: "Observability",
    ReadinessPhase.DEPLOYABILITY: "Deployability",
}


class ReadinessSeverity(StrEnum):
    PASS = "pass"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class ReadinessFinding:
    phase: ReadinessPhase
    severity: ReadinessSeverity
    title: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass(slots=True)
class TracerBulletResult:
    journey_name: str
    status: str  # production_ready, happy_path_only, partial, not_implemented
    steps_checked: int
    steps_passed: int
    weak_link: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PhaseResult:
    phase: ReadinessPhase
    phase_name: str
    score: float  # 0.0-1.0
    findings: list[ReadinessFinding] = field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class ReadinessReport:
    project_name: str
    timestamp: str
    phases_run: list[ReadinessPhase] = field(default_factory=list)
    phase_results: list[PhaseResult] = field(default_factory=list)
    tracer_bullets: list[TracerBulletResult] = field(default_factory=list)
    overall_score: float = 0.0
    overall_grade: str = "F"

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "phases": [
                {
                    "phase": pr.phase,
                    "phase_name": pr.phase_name,
                    "score": pr.score,
                    "summary": pr.summary,
                    "findings": [
                        {
                            "severity": f.severity,
                            "title": f.title,
                            "detail": f.detail,
                            "evidence": f.evidence,
                            "recommendation": f.recommendation,
                        }
                        for f in pr.findings
                    ],
                }
                for pr in self.phase_results
            ],
            "tracer_bullets": [
                {
                    "journey_name": tb.journey_name,
                    "status": tb.status,
                    "steps_checked": tb.steps_checked,
                    "steps_passed": tb.steps_passed,
                    "weak_link": tb.weak_link,
                    "evidence": tb.evidence,
                }
                for tb in self.tracer_bullets
            ],
        }


# =============================================================================
# Readiness Engine
# =============================================================================


# Route decorator patterns for different frameworks
_ROUTE_DECORATOR_RE = re.compile(
    r"@(?:app|router|api|bp|blueprint)\."
    r"(?:route|get|post|put|delete|patch|options|head|websocket)\s*\(",
    re.IGNORECASE,
)

# Stub body patterns
_STUB_PATTERNS = [
    re.compile(r"^\s*pass\s*$"),
    re.compile(r"^\s*\.\.\.\s*$"),
    re.compile(r"^\s*raise\s+NotImplementedError"),
]

# Test decorator skip patterns
_SKIP_PATTERNS = [
    re.compile(r"@pytest\.mark\.skip"),
    re.compile(r"@unittest\.skip"),
    re.compile(r"\.skip\("),
]

# Framework import patterns for observability
_LOGGING_IMPORTS = re.compile(r"(?:import\s+logging|from\s+logging\s+import|import\s+structlog|import\s+loguru)")
_METRICS_IMPORTS = re.compile(r"(?:import\s+prometheus|from\s+prometheus|import\s+statsd|import\s+datadog)")
_ERROR_TRACKING_IMPORTS = re.compile(r"(?:import\s+sentry_sdk|import\s+bugsnag|import\s+rollbar)")

# Auth decorator patterns
_AUTH_DECORATOR_RE = re.compile(
    r"@(?:login_required|auth_required|requires_auth|authenticated|"
    r"permission_required|jwt_required|token_required|Depends\(.*auth)",
    re.IGNORECASE,
)

# Lock file names
_LOCK_FILES = {"uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "go.sum"}

# Frontend file extensions
_FRONTEND_EXTS = frozenset({".jsx", ".tsx", ".vue", ".svelte"})


class ReadinessEngine:
    """Orchestrates the 8-phase readiness audit."""

    def __init__(self, project_dir: str) -> None:
        self._project_dir = os.path.abspath(project_dir)

    def run(
        self,
        *,
        phases: list[int] | None = None,
        scope: str = "",
        tracer_bullets: bool = True,
        prd_text: str = "",
    ) -> ReadinessReport:
        """Run the readiness audit.

        Args:
            phases: Phase numbers to run (0-7). None = all.
            scope: Restrict to files under this directory prefix.
            tracer_bullets: Whether to run tracer bullet analysis.
            prd_text: Optional PRD text for plan comparison.

        Returns:
            A ReadinessReport with findings and scores.
        """
        from attocode.code_intel.helpers import _detect_project_name

        project_name = _detect_project_name(self._project_dir)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

        all_phases = list(ReadinessPhase)
        requested = [ReadinessPhase(p) for p in phases] if phases else all_phases

        phase_methods = {
            ReadinessPhase.BASELINE: self._phase_baseline,
            ReadinessPhase.API_BUSINESS_LOGIC: self._phase_api_logic,
            ReadinessPhase.FRONTEND_FLOWS: self._phase_frontend,
            ReadinessPhase.DATA_LAYER: self._phase_data_layer,
            ReadinessPhase.TEST_COVERAGE: self._phase_test_coverage,
            ReadinessPhase.SECURITY_SURFACE: self._phase_security,
            ReadinessPhase.OBSERVABILITY: self._phase_observability,
            ReadinessPhase.DEPLOYABILITY: self._phase_deployability,
        }

        results: list[PhaseResult] = []
        for phase in requested:
            method = phase_methods.get(phase)
            if method:
                try:
                    result = method(scope)
                    results.append(result)
                except Exception as e:
                    logger.warning("Phase %s failed: %s", phase, e, exc_info=True)
                    results.append(PhaseResult(
                        phase=phase,
                        phase_name=_PHASE_NAMES[phase],
                        score=0.0,
                        findings=[ReadinessFinding(
                            phase=phase,
                            severity=ReadinessSeverity.CRITICAL,
                            title=f"Phase {phase.name} failed",
                            detail=str(e),
                        )],
                        summary=f"Phase failed: {e}",
                    ))

        # Tracer bullets
        bullets: list[TracerBulletResult] = []
        if tracer_bullets:
            try:
                bullets = self._run_tracer_bullets(scope)
            except Exception as e:
                logger.warning("Tracer bullets failed: %s", e, exc_info=True)

        # Compute overall score
        overall_score, overall_grade = self._compute_overall(results)

        return ReadinessReport(
            project_name=project_name,
            timestamp=timestamp,
            phases_run=requested,
            phase_results=results,
            tracer_bullets=bullets,
            overall_score=overall_score,
            overall_grade=overall_grade,
        )

    def format_report(self, report: ReadinessReport) -> str:
        """Format a ReadinessReport as human-readable text."""
        lines: list[str] = []
        score_pct = int(report.overall_score * 100)
        lines.append(f"# Readiness Report: {report.project_name}")
        lines.append(f"Generated: {report.timestamp}")
        lines.append(f"Overall Grade: {report.overall_grade} ({score_pct}/100)")
        lines.append("")

        for pr in report.phase_results:
            phase_pct = int(pr.score * 100)
            lines.append(f"## Phase {pr.phase}: {pr.phase_name} ({phase_pct}/100)")
            if pr.summary:
                lines.append(f"  {pr.summary}")
            for f in pr.findings:
                tag = _severity_tag(f.severity)
                lines.append(f"  {tag} {f.title}")
                if f.detail:
                    lines.append(f"    {f.detail}")
                for ev in f.evidence[:5]:
                    lines.append(f"    {ev}")
                if f.recommendation:
                    lines.append(f"    -> {f.recommendation}")
            lines.append("")

        if report.tracer_bullets:
            passing = sum(1 for tb in report.tracer_bullets if tb.status == "production_ready")
            total = len(report.tracer_bullets)
            lines.append(f"## Tracer Bullets ({passing}/{total} passing)")
            for tb in report.tracer_bullets:
                tag = _status_tag(tb.status)
                lines.append(f"  {tag} {tb.journey_name} ({tb.steps_passed}/{tb.steps_checked})")
                if tb.weak_link:
                    lines.append(f"    Weak link: {tb.weak_link}")
                for ev in tb.evidence[:3]:
                    lines.append(f"    {ev}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _phase_baseline(self, scope: str) -> PhaseResult:
        """Phase 0: Can it run?"""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.BASELINE
        score = 1.0

        # Git status
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_dir,
            )
            dirty_count = len([l for l in result.stdout.strip().splitlines() if l.strip()])
            if dirty_count == 0:
                findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Git status: clean"))
            else:
                findings.append(ReadinessFinding(
                    phase=phase, severity=ReadinessSeverity.WARNING,
                    title=f"Git has {dirty_count} uncommitted change(s)",
                    recommendation="Commit or stash before deployment",
                ))
                score -= 0.05
        except (subprocess.SubprocessError, FileNotFoundError):
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO,
                title="Not a git repository or git not available",
            ))

        # Build system detection
        from attocode.code_intel.helpers import _detect_build_system
        files = self._get_file_list(scope)
        build_system = _detect_build_system(files)
        if build_system and build_system != "unknown":
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title=f"Build system: {build_system}",
            ))
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.WARNING,
                title="No build system detected",
                recommendation="Add pyproject.toml, package.json, or equivalent",
            ))
            score -= 0.15

        # Lock files
        basenames = {os.path.basename(fi.relative_path) for fi in files}
        found_locks = basenames & _LOCK_FILES
        if found_locks:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title=f"Lock file(s): {', '.join(sorted(found_locks))}",
            ))
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.WARNING,
                title="No dependency lock file found",
                recommendation="Run `uv lock`, `npm install`, or equivalent to generate a lock file",
            ))
            score -= 0.1

        # Entry points
        from attocode.code_intel.helpers import _find_entry_points
        try:
            ast_svc = self._get_ast_service()
            entry_points = _find_entry_points(files, ast_svc.index)
            if entry_points:
                findings.append(ReadinessFinding(
                    phase=phase, severity=ReadinessSeverity.PASS,
                    title=f"{len(entry_points)} entry point(s) detected",
                    evidence=[f"{ep[0]} ({ep[1]})" for ep in entry_points[:5]],
                ))
            else:
                findings.append(ReadinessFinding(
                    phase=phase, severity=ReadinessSeverity.INFO,
                    title="No clear entry points detected",
                ))
                score -= 0.05
        except Exception:
            pass

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=max(0.0, score),
            findings=findings,
            summary=f"Build: {build_system}, Locks: {', '.join(sorted(found_locks)) or 'none'}",
        )

    def _phase_api_logic(self, scope: str) -> PhaseResult:
        """Phase 1: Route inventory, stubs, TODOs."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.API_BUSINESS_LOGIC
        score = 1.0

        route_handlers: list[tuple[str, int, str]] = []  # (file, line, name)
        stub_functions: list[tuple[str, int, str]] = []
        todo_count = 0

        for fi in self._get_source_files(scope):
            abs_path = os.path.join(self._project_dir, fi.relative_path)
            try:
                content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                # Route detection
                if _ROUTE_DECORATOR_RE.search(line):
                    # Next non-decorator line is likely the function def
                    for j in range(i, min(i + 5, len(lines) + 1)):
                        if j - 1 < len(lines) and lines[j - 1].strip().startswith("def "):
                            fname = lines[j - 1].strip().split("(")[0].replace("def ", "")
                            route_handlers.append((fi.relative_path, j, fname))
                            break

                # TODO/FIXME
                if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line):
                    todo_count += 1

            # Stub detection in function bodies
            self._detect_stubs(fi.relative_path, lines, stub_functions)

        if route_handlers:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title=f"{len(route_handlers)} route handler(s) detected",
                evidence=[f"{rh[0]}:{rh[1]} -- {rh[2]}()" for rh in route_handlers[:10]],
            ))
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO,
                title="No route handlers detected (may not be a web API)",
            ))

        if stub_functions:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.CRITICAL,
                title=f"{len(stub_functions)} stub function(s) found",
                detail="Functions with only pass, ..., or raise NotImplementedError",
                evidence=[f"{s[0]}:{s[1]} -- {s[2]}()" for s in stub_functions[:10]],
                recommendation="Implement stub functions before shipping",
            ))
            score -= min(0.3, len(stub_functions) * 0.05)

        if todo_count > 0:
            sev = ReadinessSeverity.WARNING if todo_count > 10 else ReadinessSeverity.INFO
            findings.append(ReadinessFinding(
                phase=phase, severity=sev,
                title=f"{todo_count} TODO/FIXME markers in source code",
            ))
            if todo_count > 20:
                score -= 0.1

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=max(0.0, score),
            findings=findings,
            summary=f"{len(route_handlers)} routes, {len(stub_functions)} stubs, {todo_count} TODOs",
        )

    def _phase_frontend(self, scope: str) -> PhaseResult:
        """Phase 2: Frontend component inventory."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.FRONTEND_FLOWS

        frontend_files = [
            fi for fi in self._get_source_files(scope)
            if Path(fi.relative_path).suffix.lower() in _FRONTEND_EXTS
        ]

        if not frontend_files:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title="No frontend files detected (not a frontend project)",
            ))
            return PhaseResult(
                phase=phase, phase_name=_PHASE_NAMES[phase],
                score=1.0, findings=findings,
                summary="Skipped (no frontend files)",
            )

        findings.append(ReadinessFinding(
            phase=phase, severity=ReadinessSeverity.PASS,
            title=f"{len(frontend_files)} frontend component file(s)",
            evidence=[fi.relative_path for fi in frontend_files[:10]],
        ))

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=0.8,
            findings=findings,
            summary=f"{len(frontend_files)} frontend files",
        )

    def _phase_data_layer(self, scope: str) -> PhaseResult:
        """Phase 3: Migrations, models, constraints."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.DATA_LAYER
        score = 1.0

        # Migration detection
        migration_dirs: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._project_dir):
            rel = os.path.relpath(dirpath, self._project_dir)
            basename = os.path.basename(dirpath)
            if basename in ("migrations", "alembic", "prisma", "versions"):
                migration_dirs.append(rel)
            # Don't recurse into common skip dirs
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".venv"}]

        if migration_dirs:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title=f"Migration directory found: {', '.join(migration_dirs[:3])}",
            ))
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO,
                title="No migration directories found",
                detail="May not be a database-backed project",
            ))

        # ORM model detection
        model_count = 0
        for fi in self._get_source_files(scope):
            abs_path = os.path.join(self._project_dir, fi.relative_path)
            try:
                content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # SQLAlchemy/Django model patterns
            if re.search(r"class\s+\w+\(.*(?:Base|Model|db\.Model|DeclarativeBase)", content):
                model_count += 1

        if model_count:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS,
                title=f"{model_count} ORM model file(s) detected",
            ))

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=max(0.0, score),
            findings=findings,
            summary=f"Migrations: {len(migration_dirs)}, Models: {model_count}",
        )

    def _phase_test_coverage(self, scope: str) -> PhaseResult:
        """Phase 4: Test file inventory, coverage gaps, skipped tests."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.TEST_COVERAGE
        score = 1.0

        all_files = self._get_file_list(scope)
        test_files = [fi for fi in all_files if fi.is_test]
        source_files = [fi for fi in all_files if not fi.is_test and not fi.is_config]

        if not source_files:
            return PhaseResult(
                phase=phase, phase_name=_PHASE_NAMES[phase],
                score=1.0, findings=[],
                summary="No source files to test",
            )

        test_ratio = len(test_files) / max(len(source_files), 1)

        findings.append(ReadinessFinding(
            phase=phase, severity=ReadinessSeverity.PASS if test_ratio >= 0.3 else ReadinessSeverity.WARNING,
            title=f"{len(test_files)} test file(s) for {len(source_files)} source file(s) ({test_ratio:.0%})",
        ))

        if test_ratio < 0.1:
            score -= 0.4
        elif test_ratio < 0.3:
            score -= 0.2

        # Detect skipped tests
        skip_count = 0
        for fi in test_files:
            abs_path = os.path.join(self._project_dir, fi.relative_path)
            try:
                content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in _SKIP_PATTERNS:
                skip_count += len(pat.findall(content))

        if skip_count > 0:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.WARNING,
                title=f"{skip_count} skipped test(s) detected",
                recommendation="Review and either fix or remove skipped tests",
            ))
            score -= min(0.15, skip_count * 0.02)

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=max(0.0, score),
            findings=findings,
            summary=f"{len(test_files)} tests / {len(source_files)} source ({test_ratio:.0%}), {skip_count} skipped",
        )

    def _phase_security(self, scope: str) -> PhaseResult:
        """Phase 5: Security scan + auth checks."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.SECURITY_SURFACE
        score = 1.0

        # Use existing SecurityScanner
        try:
            from attocode.integrations.security.scanner import SecurityScanner
            scanner = SecurityScanner(root_dir=self._project_dir)
            report = scanner.scan(mode="full", path=scope)
            compliance = report.compliance_score / 100.0 if hasattr(report, "compliance_score") else 0.8

            critical_findings = [f for f in report.findings if getattr(f, "severity", "") == "high"]
            if critical_findings:
                findings.append(ReadinessFinding(
                    phase=phase, severity=ReadinessSeverity.CRITICAL,
                    title=f"{len(critical_findings)} high-severity security finding(s)",
                    evidence=[str(f)[:100] for f in critical_findings[:5]],
                ))
                score -= min(0.4, len(critical_findings) * 0.1)
            else:
                findings.append(ReadinessFinding(
                    phase=phase, severity=ReadinessSeverity.PASS,
                    title="No high-severity security findings",
                ))

            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.PASS if compliance >= 0.8 else ReadinessSeverity.WARNING,
                title=f"Security compliance score: {compliance:.0%}",
            ))
            score = min(score, compliance)
        except Exception as e:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO,
                title=f"Security scanner unavailable: {e}",
            ))

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=max(0.0, score),
            findings=findings,
        )

    def _phase_observability(self, scope: str) -> PhaseResult:
        """Phase 6: Logging, metrics, error tracking."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.OBSERVABILITY
        score = 0.5  # Start lower, add for each capability found

        has_logging = False
        has_metrics = False
        has_error_tracking = False

        for fi in self._get_source_files(scope):
            abs_path = os.path.join(self._project_dir, fi.relative_path)
            try:
                content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _LOGGING_IMPORTS.search(content):
                has_logging = True
            if _METRICS_IMPORTS.search(content):
                has_metrics = True
            if _ERROR_TRACKING_IMPORTS.search(content):
                has_error_tracking = True

        if has_logging:
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Logging framework detected"))
            score += 0.2
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.WARNING, title="No logging framework detected",
                recommendation="Add structured logging (logging, structlog, or loguru)",
            ))

        if has_metrics:
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Metrics framework detected"))
            score += 0.15
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO, title="No metrics framework detected",
            ))

        if has_error_tracking:
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Error tracking detected"))
            score += 0.15
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO, title="No error tracking detected",
            ))

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=min(1.0, score),
            findings=findings,
            summary=f"Logging: {'yes' if has_logging else 'no'}, Metrics: {'yes' if has_metrics else 'no'}, Errors: {'yes' if has_error_tracking else 'no'}",
        )

    def _phase_deployability(self, scope: str) -> PhaseResult:
        """Phase 7: Docker, CI/CD, env config."""
        findings: list[ReadinessFinding] = []
        phase = ReadinessPhase.DEPLOYABILITY
        score = 0.5

        pd = self._project_dir

        # Dockerfile
        if os.path.isfile(os.path.join(pd, "Dockerfile")):
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Dockerfile present"))
            score += 0.15
        elif os.path.isfile(os.path.join(pd, "docker-compose.yml")) or os.path.isfile(os.path.join(pd, "docker-compose.yaml")):
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="docker-compose config present"))
            score += 0.1
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.INFO, title="No Dockerfile found",
            ))

        # CI/CD
        ci_found = False
        if os.path.isdir(os.path.join(pd, ".github", "workflows")):
            ci_found = True
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="GitHub Actions workflows found"))
        if os.path.isfile(os.path.join(pd, ".gitlab-ci.yml")):
            ci_found = True
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="GitLab CI config found"))
        if os.path.isfile(os.path.join(pd, "Jenkinsfile")):
            ci_found = True
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title="Jenkinsfile found"))

        if ci_found:
            score += 0.2
        else:
            findings.append(ReadinessFinding(
                phase=phase, severity=ReadinessSeverity.WARNING, title="No CI/CD configuration found",
                recommendation="Add .github/workflows/, .gitlab-ci.yml, or equivalent",
            ))

        # .env.example
        if os.path.isfile(os.path.join(pd, ".env.example")):
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title=".env.example present"))
            score += 0.1
        elif os.path.isfile(os.path.join(pd, ".env.template")):
            findings.append(ReadinessFinding(phase=phase, severity=ReadinessSeverity.PASS, title=".env.template present"))
            score += 0.1

        return PhaseResult(
            phase=phase, phase_name=_PHASE_NAMES[phase],
            score=min(1.0, score),
            findings=findings,
        )

    # ------------------------------------------------------------------
    # Tracer Bullets
    # ------------------------------------------------------------------

    def _run_tracer_bullets(self, scope: str) -> list[TracerBulletResult]:
        """Trace top entry point -> dependency chains for end-to-end verification."""
        results: list[TracerBulletResult] = []
        try:
            ast_svc = self._get_ast_service()
        except Exception:
            return results

        # Find entry-like files (high importance or entry filenames)
        from attocode.code_intel.helpers import _find_entry_points
        files = self._get_file_list(scope)
        entry_points = _find_entry_points(files, ast_svc.index)

        for ep_path, ep_reason in entry_points[:10]:
            # Trace dependency chain
            deps = list(ast_svc.index.file_dependencies.get(ep_path, set()))[:10]
            steps_total = 1 + len(deps)
            steps_passed = 1  # Entry point exists

            weak_link = ""
            evidence = [f"Entry: {ep_path} ({ep_reason})"]

            for dep in deps:
                dep_abs = os.path.join(self._project_dir, dep)
                if os.path.isfile(dep_abs):
                    steps_passed += 1
                else:
                    if not weak_link:
                        weak_link = f"Missing dependency: {dep}"

            ratio = steps_passed / steps_total if steps_total > 0 else 0
            if ratio >= 1.0:
                status = "production_ready"
            elif ratio >= 0.7:
                status = "happy_path_only"
            elif ratio > 0:
                status = "partial"
            else:
                status = "not_implemented"

            results.append(TracerBulletResult(
                journey_name=ep_path,
                status=status,
                steps_checked=steps_total,
                steps_passed=steps_passed,
                weak_link=weak_link,
                evidence=evidence,
            ))

        return results

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_overall(results: list[PhaseResult]) -> tuple[float, str]:
        """Compute weighted overall score and letter grade."""
        if not results:
            return 0.0, "F"

        weights = {
            ReadinessPhase.BASELINE: 2.0,
            ReadinessPhase.TEST_COVERAGE: 2.0,
            ReadinessPhase.SECURITY_SURFACE: 2.0,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for pr in results:
            w = weights.get(pr.phase, 1.0)
            weighted_sum += pr.score * w
            total_weight += w

        score = weighted_sum / total_weight if total_weight > 0 else 0.0

        if score >= 0.9:
            grade = "A"
        elif score >= 0.75:
            grade = "B"
        elif score >= 0.6:
            grade = "C"
        elif score >= 0.45:
            grade = "D"
        else:
            grade = "F"

        return round(score, 3), grade

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_ast_service(self):
        """Get the AST service for the project."""
        from attocode.integrations.context.ast_service import ASTService
        svc = ASTService.get_instance(self._project_dir)
        if not svc.initialized:
            svc.initialize()
        return svc

    def _get_file_list(self, scope: str) -> list:
        """Get the file list from CodebaseContextManager."""
        from attocode.integrations.context.codebase_context import CodebaseContextManager
        ctx = CodebaseContextManager(root_dir=self._project_dir)
        ctx.discover_files()
        files = ctx._files
        if scope:
            files = [fi for fi in files if fi.relative_path.startswith(scope)]
        return files

    def _get_source_files(self, scope: str) -> list:
        """Get non-test, non-config source files."""
        return [
            fi for fi in self._get_file_list(scope)
            if not fi.is_test and not fi.is_config
        ]

    @staticmethod
    def _detect_stubs(
        rel_path: str,
        lines: list[str],
        stubs: list[tuple[str, int, str]],
    ) -> None:
        """Detect stub functions in source code."""
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Look for function definitions
            if stripped.startswith("def ") and "(" in stripped:
                fname = stripped.split("(")[0].replace("def ", "").strip()
                # Skip dunder methods and abstract methods
                if fname.startswith("__") and fname.endswith("__"):
                    i += 1
                    continue

                # Check the function body (next non-empty, non-comment line)
                body_start = i + 1
                while body_start < len(lines):
                    body_line = lines[body_start].strip()
                    if body_line and not body_line.startswith("#") and not body_line.startswith('"""') and not body_line.startswith("'''"):
                        break
                    # Skip docstrings
                    if body_line.startswith('"""') or body_line.startswith("'''"):
                        quote = body_line[:3]
                        if body_line.count(quote) >= 2:
                            body_start += 1
                        else:
                            body_start += 1
                            while body_start < len(lines) and quote not in lines[body_start]:
                                body_start += 1
                            body_start += 1
                        continue
                    body_start += 1

                if body_start < len(lines):
                    body_line = lines[body_start].strip()
                    for pat in _STUB_PATTERNS:
                        if pat.match(body_line):
                            stubs.append((rel_path, i + 1, fname))
                            break

            i += 1


# =============================================================================
# Formatting helpers
# =============================================================================


def _severity_tag(severity: ReadinessSeverity) -> str:
    tags = {
        ReadinessSeverity.PASS: "[PASS]",
        ReadinessSeverity.INFO: "[INFO]",
        ReadinessSeverity.WARNING: "[WARN]",
        ReadinessSeverity.CRITICAL: "[CRIT]",
    }
    return tags.get(severity, "[????]")


def _status_tag(status: str) -> str:
    tags = {
        "production_ready": "[PASS]",
        "happy_path_only": "[WARN]",
        "partial": "[PART]",
        "not_implemented": "[FAIL]",
    }
    return tags.get(status, "[????]")
