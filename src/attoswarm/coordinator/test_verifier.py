"""Test verification gate for SwarmOrchestrator.

Detects test commands, scopes tests to changed files where possible, runs
them as a subprocess, and parses pass/fail results.  Reuses patterns from
``research/evaluator.py:TestPassRateEvaluator``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TestVerificationResult:
    """Outcome of running the test verification gate."""

    passed: bool
    pass_rate: float
    tests_passed: int
    tests_failed: int
    tests_total: int
    raw_output: str
    error: str = ""
    duration_s: float = 0.0


# ── Test command detection ────────────────────────────────────────────


def detect_test_command(working_dir: str) -> str | None:
    """Auto-detect the project's test command by probing config files.

    Checks (in order): pyproject.toml, pytest.ini, setup.cfg, package.json,
    Makefile, Cargo.toml, go.mod.  Returns ``None`` if nothing found.
    """
    root = Path(working_dir)

    # Python: pytest is most common
    for marker in ("pyproject.toml", "pytest.ini", "setup.cfg"):
        if (root / marker).exists():
            return "python -m pytest --tb=short -q"

    # Node.js
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json

            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "npm test"
        except Exception:
            pass

    # Makefile with test target
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            text = makefile.read_text(encoding="utf-8")
            if re.search(r"^test:", text, re.MULTILINE):
                return "make test"
        except Exception:
            pass

    # Rust
    if (root / "Cargo.toml").exists():
        return "cargo test"

    # Go
    if (root / "go.mod").exists():
        return "go test ./..."

    return None


# ── Test scoping ──────────────────────────────────────────────────────


def scope_tests_to_files(
    test_command: str,
    files_modified: list[str],
    working_dir: str,
) -> str:
    """Narrow the test command to only test files related to the changes.

    For pytest, discovers matching ``test_*.py`` or ``*_test.py`` files.
    For other frameworks, returns the original command (run full suite).
    """
    if "pytest" not in test_command:
        return test_command

    root = Path(working_dir)
    test_files: list[str] = []

    for fpath in files_modified:
        p = Path(fpath)
        stem = p.stem
        parent = root / p.parent if not p.is_absolute() else p.parent

        # Direct: modified file is itself a test
        if stem.startswith("test_") or stem.endswith("_test"):
            candidate = root / fpath
            if candidate.exists():
                test_files.append(str(candidate))
                continue

        # Heuristic: look for test_<stem>.py or <stem>_test.py in same dir and tests/ dirs
        for search_dir in [parent, root / "tests", root / "test"]:
            if not search_dir.is_dir():
                continue
            for pattern in [f"test_{stem}.py", f"{stem}_test.py"]:
                matches = list(search_dir.glob(pattern))
                test_files.extend(str(m) for m in matches)

    if test_files:
        unique = sorted(set(test_files))[:20]  # cap at 20 test files
        return f"{test_command} {' '.join(unique)}"

    return test_command


# ── Pytest output parsing ─────────────────────────────────────────────

# Patterns from research/evaluator.py
_PYTEST_SUMMARY_RE = re.compile(
    r"(\d+)\s+passed(?:.*?(\d+)\s+failed)?(?:.*?(\d+)\s+error)?",
)
_PYTEST_SHORT_RE = re.compile(r"(\d+)\s+passed")
_PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed")
_PYTEST_ERRORS_RE = re.compile(r"(\d+)\s+error")


def _parse_pytest_output(output: str) -> tuple[int, int, int]:
    """Parse pytest output for passed/failed/total counts.

    Returns ``(passed, failed, total)``.
    """
    passed = 0
    failed = 0
    errors = 0

    # Try summary line first (e.g. "5 passed, 2 failed, 1 error")
    m = _PYTEST_SUMMARY_RE.search(output)
    if m:
        passed = int(m.group(1))
        failed = int(m.group(2) or 0)
        errors = int(m.group(3) or 0)
        return passed, failed + errors, passed + failed + errors

    # Fallback: search for individual patterns
    m_pass = _PYTEST_SHORT_RE.search(output)
    if m_pass:
        passed = int(m_pass.group(1))
    m_fail = _PYTEST_FAILED_RE.search(output)
    if m_fail:
        failed = int(m_fail.group(1))
    m_err = _PYTEST_ERRORS_RE.search(output)
    if m_err:
        errors = int(m_err.group(1))

    total = passed + failed + errors
    return passed, failed + errors, total


# ── Test execution ────────────────────────────────────────────────────


async def run_test_verification(
    working_dir: str,
    test_command: str,
    timeout: float,
    files_modified: list[str] | None = None,
    scope: bool = True,
) -> TestVerificationResult:
    """Run the test command and parse the result.

    If *scope* is True and *files_modified* is provided, attempts to narrow
    the test run to related test files (pytest only).
    """
    cmd = test_command
    if scope and files_modified:
        cmd = scope_tests_to_files(test_command, files_modified, working_dir)

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=working_dir,
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            return TestVerificationResult(
                passed=False,
                pass_rate=0.0,
                tests_passed=0,
                tests_failed=0,
                tests_total=0,
                raw_output="",
                error=f"Test command timed out after {timeout}s",
                duration_s=time.monotonic() - t0,
            )

        duration = time.monotonic() - t0
        output = (stdout_bytes or b"").decode("utf-8", errors="replace")

        # Try pytest-specific parsing
        if "pytest" in test_command:
            passed, failed, total = _parse_pytest_output(output)
        else:
            # Generic: exit code 0 = pass
            total = 1
            if proc.returncode == 0:
                passed, failed = 1, 0
            else:
                passed, failed = 0, 1

        pass_rate = passed / total if total > 0 else 1.0

        return TestVerificationResult(
            passed=proc.returncode == 0 and failed == 0,
            pass_rate=pass_rate,
            tests_passed=passed,
            tests_failed=failed,
            tests_total=total,
            raw_output=output[-4000:],  # keep last 4k chars
            duration_s=duration,
        )

    except Exception as exc:
        return TestVerificationResult(
            passed=False,
            pass_rate=0.0,
            tests_passed=0,
            tests_failed=0,
            tests_total=0,
            raw_output="",
            error=str(exc),
            duration_s=time.monotonic() - t0,
        )
