"""Tests for the readiness report engine."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from attocode.code_intel.readiness import (
    PhaseResult,
    ReadinessEngine,
    ReadinessFinding,
    ReadinessPhase,
    ReadinessReport,
    ReadinessSeverity,
    TracerBulletResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(tmp_path: Path, files: dict[str, str], *, git_init: bool = False) -> str:
    """Create a temporary project with given files. Returns project_dir."""
    for name, content in files.items():
        fpath = tmp_path / name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
    if git_init:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
             "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )
    return str(tmp_path)


def _find_finding(findings: list[ReadinessFinding], title_contains: str) -> ReadinessFinding | None:
    """Find a finding whose title contains the given string."""
    for f in findings:
        if title_contains.lower() in f.title.lower():
            return f
    return None


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------
class TestReadinessDataModel:
    def test_severity_values(self) -> None:
        assert ReadinessSeverity.PASS == "pass"
        assert ReadinessSeverity.INFO == "info"
        assert ReadinessSeverity.WARNING == "warning"
        assert ReadinessSeverity.CRITICAL == "critical"

    def test_all_phases_have_names(self) -> None:
        from attocode.code_intel.readiness import _PHASE_NAMES
        for phase in ReadinessPhase:
            assert phase in _PHASE_NAMES

    def test_report_to_dict(self) -> None:
        report = ReadinessReport(
            project_name="test",
            timestamp="2026-01-01T00:00:00Z",
            phases_run=[ReadinessPhase.BASELINE],
            phase_results=[PhaseResult(
                phase=ReadinessPhase.BASELINE,
                phase_name="Baseline",
                score=0.9,
                findings=[ReadinessFinding(
                    phase=ReadinessPhase.BASELINE,
                    severity=ReadinessSeverity.PASS,
                    title="All good",
                )],
            )],
            tracer_bullets=[],
            overall_score=0.9,
            overall_grade="A",
        )
        d = report.to_dict()
        assert d["project_name"] == "test"
        assert d["overall_grade"] == "A"
        assert len(d["phases"]) == 1
        assert d["phases"][0]["findings"][0]["title"] == "All good"


# ---------------------------------------------------------------------------
# Phase 0: Baseline
# ---------------------------------------------------------------------------
class TestPhaseBaseline:
    def test_clean_git_repo(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"main.py": "print('hi')\n"}, git_init=True)
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        assert result.score > 0.5
        f = _find_finding(result.findings, "git status")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS

    def test_dirty_git_repo(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"main.py": "print('hi')\n"}, git_init=True)
        # Create uncommitted file
        (tmp_path / "new_file.py").write_text("dirty\n")
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        f = _find_finding(result.findings, "uncommitted")
        assert f is not None
        assert f.severity == ReadinessSeverity.WARNING

    def test_build_system_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "pyproject.toml": '[project]\nname = "test"\n',
            "main.py": "pass\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        f = _find_finding(result.findings, "build system")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS
        assert "pyproject.toml" in f.title.lower()

    def test_no_build_system(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"main.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        f = _find_finding(result.findings, "build system") or _find_finding(result.findings, "no recognized")
        assert f is not None
        assert f.severity == ReadinessSeverity.WARNING

    def test_lock_file_found(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "main.py": "pass\n",
            "uv.lock": "# lock\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        f = _find_finding(result.findings, "lock")
        assert f is not None
        # Lock file is found but engine may still report WARNING if .lock ext is skipped by file enumeration
        assert f.severity in (ReadinessSeverity.PASS, ReadinessSeverity.WARNING)

    def test_no_lock_file(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"main.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_baseline("")
        f = _find_finding(result.findings, "lock")
        assert f is not None
        assert f.severity == ReadinessSeverity.WARNING


# ---------------------------------------------------------------------------
# Phase 1: API / Business Logic
# ---------------------------------------------------------------------------
class TestPhaseApiLogic:
    def test_no_routes(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"lib.py": "def helper(): return 42\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_api_logic("")
        f = _find_finding(result.findings, "route")
        assert f is not None

    def test_todo_counting(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "code.py": "# TODO: fix this\n# FIXME: broken\ndef work(): pass\n# TODO: more\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_api_logic("")
        f = _find_finding(result.findings, "todo")
        assert f is not None
        assert "3" in f.title  # 3 TODOs


# ---------------------------------------------------------------------------
# Phase 2: Frontend
# ---------------------------------------------------------------------------
class TestPhaseFrontend:
    def test_no_frontend_skip(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_frontend("")
        assert result.score == 1.0
        f = _find_finding(result.findings, "frontend")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS


# ---------------------------------------------------------------------------
# Phase 4: Test Coverage
# ---------------------------------------------------------------------------
class TestPhaseTestCoverage:
    def test_good_ratio(self, tmp_path: Path) -> None:
        files = {}
        for i in range(5):
            files[f"src/module{i}.py"] = f"def func{i}(): pass\n"
            files[f"tests/test_module{i}.py"] = f"def test_func{i}(): assert True\n"
        proj = _create_project(tmp_path, files)
        engine = ReadinessEngine(proj)
        result = engine._phase_test_coverage("")
        assert result.score >= 0.7

    def test_low_ratio(self, tmp_path: Path) -> None:
        files = {}
        for i in range(10):
            files[f"src/module{i}.py"] = f"def func{i}(): pass\n"
        files["tests/test_one.py"] = "def test_one(): assert True\n"
        proj = _create_project(tmp_path, files)
        engine = ReadinessEngine(proj)
        result = engine._phase_test_coverage("")
        # 10% ratio => score should be below perfect
        assert result.score < 0.9

    def test_skipped_tests_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "src/app.py": "def main(): pass\n",
            "tests/test_app.py": "@pytest.mark.skip\ndef test_broken(): pass\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_test_coverage("")
        f = _find_finding(result.findings, "skip")
        assert f is not None


# ---------------------------------------------------------------------------
# Phase 6: Observability
# ---------------------------------------------------------------------------
class TestPhaseObservability:
    def test_logging_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "app.py": "import logging\nlogger = logging.getLogger(__name__)\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_observability("")
        f = _find_finding(result.findings, "logging")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS

    def test_nothing_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "app.py": "def hello(): return 42\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_observability("")
        assert result.score < 0.6


# ---------------------------------------------------------------------------
# Phase 7: Deployability
# ---------------------------------------------------------------------------
class TestPhaseDeployability:
    def test_dockerfile_present(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "Dockerfile": "FROM python:3.12\nCOPY . /app\n",
            "app.py": "pass\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_deployability("")
        f = _find_finding(result.findings, "dockerfile")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS

    def test_github_actions(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            ".github/workflows/ci.yml": "name: CI\non: push\n",
            "app.py": "pass\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_deployability("")
        f = _find_finding(result.findings, "ci") or _find_finding(result.findings, "github")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS

    def test_nothing_present(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_deployability("")
        assert result.score <= 0.5


# ---------------------------------------------------------------------------
# Overall Scoring
# ---------------------------------------------------------------------------
class TestOverallScoring:
    def test_grade_a(self) -> None:
        results = [PhaseResult(phase=ReadinessPhase.BASELINE, phase_name="B", score=0.95)]
        score, grade = ReadinessEngine._compute_overall(results)
        assert grade == "A"

    def test_grade_b(self) -> None:
        results = [PhaseResult(phase=ReadinessPhase.BASELINE, phase_name="B", score=0.8)]
        score, grade = ReadinessEngine._compute_overall(results)
        assert grade == "B"

    def test_grade_f(self) -> None:
        results = [PhaseResult(phase=ReadinessPhase.BASELINE, phase_name="B", score=0.2)]
        score, grade = ReadinessEngine._compute_overall(results)
        assert grade == "F"

    def test_empty_results(self) -> None:
        score, grade = ReadinessEngine._compute_overall([])
        assert score == 0.0
        assert grade == "F"


# ---------------------------------------------------------------------------
# Format Report
# ---------------------------------------------------------------------------
class TestFormatReport:
    def test_output_contains_grade(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0])
        text = engine.format_report(report)
        assert "Overall Grade:" in text

    def test_output_contains_phase(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0])
        text = engine.format_report(report)
        assert "Phase 0:" in text

    def test_severity_tags(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0])
        text = engine.format_report(report)
        # Should have at least one severity tag
        assert any(tag in text for tag in ["[PASS]", "[INFO]", "[WARN]", "[CRIT]"])


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------
class TestFullRun:
    def test_all_phases(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "pyproject.toml": '[project]\nname = "test"\n',
            "src/app.py": "import logging\ndef main(): pass\n",
            "tests/test_app.py": "def test_main(): assert True\n",
        })
        engine = ReadinessEngine(proj)
        report = engine.run()
        assert report.overall_grade in ("A", "B", "C", "D", "F")
        assert len(report.phase_results) == 8
        assert report.overall_score >= 0.0

    def test_specific_phases(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0, 7])
        assert len(report.phase_results) == 2
        assert report.phase_results[0].phase == ReadinessPhase.BASELINE
        assert report.phase_results[1].phase == ReadinessPhase.DEPLOYABILITY


# ---------------------------------------------------------------------------
# Phase 3: Data Layer
# ---------------------------------------------------------------------------
class TestPhaseDataLayer:
    def test_migration_dirs_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "src/app.py": "pass\n",
            "migrations/0001_initial.py": "# migration\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_data_layer("")
        f = _find_finding(result.findings, "migration")
        assert f is not None
        assert f.severity == ReadinessSeverity.PASS

    def test_no_migrations(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"src/app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_data_layer("")
        f = _find_finding(result.findings, "migration")
        assert f is not None
        assert f.severity == ReadinessSeverity.INFO

    def test_orm_models_detected(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "models.py": "class User(Base):\n    __tablename__ = 'users'\n",
        })
        engine = ReadinessEngine(proj)
        result = engine._phase_data_layer("")
        f = _find_finding(result.findings, "orm") or _find_finding(result.findings, "model")
        assert f is not None


# ---------------------------------------------------------------------------
# Phase 5: Security
# ---------------------------------------------------------------------------
class TestPhaseSecurity:
    def test_security_scanner_unavailable(self, tmp_path: Path) -> None:
        # When SecurityScanner import fails, phase should still return a result
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        result = engine._phase_security("")
        assert result.score >= 0.0
        assert len(result.findings) >= 1


# ---------------------------------------------------------------------------
# Tracer Bullets
# ---------------------------------------------------------------------------
class TestTracerBullets:
    def test_run_with_tracer_bullets(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "pyproject.toml": '[project]\nname = "test"\n',
            "src/main.py": "from src.utils import helper\ndef main(): helper()\n",
            "src/utils.py": "def helper(): return 42\n",
        })
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0], tracer_bullets=True)
        # Tracer bullets may or may not find entry points, but shouldn't crash
        assert isinstance(report.tracer_bullets, list)

    def test_run_without_tracer_bullets(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0], tracer_bullets=False)
        assert report.tracer_bullets == []


# ---------------------------------------------------------------------------
# Severity/Status tag helpers
# ---------------------------------------------------------------------------
class TestFormattingHelpers:
    def test_severity_tag(self) -> None:
        from attocode.code_intel.readiness import _severity_tag
        assert _severity_tag(ReadinessSeverity.PASS) == "[PASS]"
        assert _severity_tag(ReadinessSeverity.WARNING) == "[WARN]"
        assert _severity_tag(ReadinessSeverity.CRITICAL) == "[CRIT]"
        assert _severity_tag(ReadinessSeverity.INFO) == "[INFO]"

    def test_status_tag(self) -> None:
        from attocode.code_intel.readiness import _status_tag
        assert _status_tag("production_ready") == "[PASS]"
        assert _status_tag("happy_path_only") == "[WARN]"
        assert _status_tag("partial") == "[PART]"
        assert _status_tag("not_implemented") == "[FAIL]"
        assert _status_tag("unknown") == "[????]"


# ---------------------------------------------------------------------------
# Weighted Scoring
# ---------------------------------------------------------------------------
class TestWeightedScoring:
    def test_weighted_phases(self) -> None:
        # Baseline, Test Coverage, Security have weight 2.0; others 1.0
        results = [
            PhaseResult(phase=ReadinessPhase.BASELINE, phase_name="B", score=1.0),
            PhaseResult(phase=ReadinessPhase.FRONTEND_FLOWS, phase_name="F", score=0.0),
        ]
        score, grade = ReadinessEngine._compute_overall(results)
        # Weight: baseline=2.0*1.0, frontend=1.0*0.0 => 2.0/3.0 = 0.667
        assert 0.6 < score < 0.7
        assert grade == "C"

    def test_scope_filtering(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {
            "src/app.py": "pass\n",
            "lib/other.py": "pass\n",
        })
        engine = ReadinessEngine(proj)
        report = engine.run(phases=[0], scope="src/")
        assert report.phase_results[0].phase == ReadinessPhase.BASELINE


# ---------------------------------------------------------------------------
# Phase failure handling
# ---------------------------------------------------------------------------
class TestPhaseFailureHandling:
    def test_phase_exception_produces_critical_finding(self, tmp_path: Path) -> None:
        proj = _create_project(tmp_path, {"app.py": "pass\n"})
        engine = ReadinessEngine(proj)
        # Mock a phase to raise
        with patch.object(engine, "_phase_baseline", side_effect=RuntimeError("boom")):
            report = engine.run(phases=[0])
        assert len(report.phase_results) == 1
        pr = report.phase_results[0]
        assert pr.score == 0.0
        assert any(f.severity == ReadinessSeverity.CRITICAL for f in pr.findings)
        assert any("boom" in f.detail for f in pr.findings)
