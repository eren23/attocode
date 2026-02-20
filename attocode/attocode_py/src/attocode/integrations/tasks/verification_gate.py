"""Post-task verification gate.

Runs automated checks (tests, type-checking, linting) and optionally
an LLM-based review to verify that a subtask was completed correctly.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol

from attocode.integrations.tasks.task_splitter import SubTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckResult:
    """Outcome of a single verification check."""

    name: str
    passed: bool
    message: str = ""


@dataclass(slots=True)
class VerificationResult:
    """Aggregate result of all verification checks for a task."""

    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM provider protocol
# ---------------------------------------------------------------------------


class _LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 800,
        temperature: float = 0.1,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_verification_prompt(task: SubTask, result: str) -> str:
    """Build an LLM prompt to evaluate whether a task result is acceptable."""
    return (
        "You are a code-review verification assistant. Evaluate whether "
        "the following task was completed correctly.\n\n"
        f"## Task\n**{task.id}:** {task.description}\n\n"
        f"## Result\n{result}\n\n"
        "## Instructions\n"
        "Assess whether the result fulfils the task requirements.\n"
        "Respond with exactly two lines:\n"
        "PASSED: true or false\n"
        "FEEDBACK: one-sentence summary of your assessment"
    )


# ---------------------------------------------------------------------------
# Subprocess check helpers
# ---------------------------------------------------------------------------

_TIMEOUT_SECONDS = 120


def _run_command(
    cmd: list[str],
    working_dir: str,
) -> tuple[bool, str]:
    """Run a command and return ``(success, output)``."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output
    except FileNotFoundError:
        return True, f"Command not found: {cmd[0]} (skipped)"
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return False, f"OS error: {exc}"


def check_tests_pass(working_dir: str) -> CheckResult:
    """Run the project test suite and return a :class:`CheckResult`.

    Tries ``pytest`` first, then falls back to ``npm test`` if a
    ``package.json`` is present.
    """
    # Try pytest
    if os.path.isfile(os.path.join(working_dir, "pyproject.toml")) or os.path.isdir(
        os.path.join(working_dir, "tests")
    ):
        passed, output = _run_command(["python", "-m", "pytest", "--tb=short", "-q"], working_dir)
        return CheckResult(name="tests", passed=passed, message=output[:500])

    # Try npm test
    if os.path.isfile(os.path.join(working_dir, "package.json")):
        passed, output = _run_command(["npm", "test", "--", "--passWithNoTests"], working_dir)
        return CheckResult(name="tests", passed=passed, message=output[:500])

    return CheckResult(name="tests", passed=True, message="No test runner detected (skipped)")


def check_type_errors(working_dir: str) -> CheckResult:
    """Run the type checker and return a :class:`CheckResult`.

    Tries ``mypy`` for Python projects, ``npx tsc --noEmit`` for
    TypeScript projects.
    """
    # Python: mypy
    if os.path.isfile(os.path.join(working_dir, "pyproject.toml")):
        passed, output = _run_command(["python", "-m", "mypy", "."], working_dir)
        return CheckResult(name="type_check", passed=passed, message=output[:500])

    # TypeScript: tsc
    if os.path.isfile(os.path.join(working_dir, "tsconfig.json")):
        passed, output = _run_command(["npx", "tsc", "--noEmit"], working_dir)
        return CheckResult(name="type_check", passed=passed, message=output[:500])

    return CheckResult(
        name="type_check", passed=True, message="No type checker detected (skipped)"
    )


def check_lint(working_dir: str) -> CheckResult:
    """Run the linter and return a :class:`CheckResult`.

    Tries ``ruff`` for Python, ``npx eslint`` for JavaScript/TypeScript.
    """
    # Python: ruff
    if os.path.isfile(os.path.join(working_dir, "pyproject.toml")):
        passed, output = _run_command(["python", "-m", "ruff", "check", "."], working_dir)
        return CheckResult(name="lint", passed=passed, message=output[:500])

    # JS/TS: eslint
    if os.path.isfile(os.path.join(working_dir, "package.json")):
        passed, output = _run_command(["npx", "eslint", "."], working_dir)
        return CheckResult(name="lint", passed=passed, message=output[:500])

    return CheckResult(name="lint", passed=True, message="No linter detected (skipped)")


# ---------------------------------------------------------------------------
# VerificationGate
# ---------------------------------------------------------------------------


class VerificationGate:
    """Post-task verification combining automated checks and LLM review.

    Runs filesystem checks (tests, types, lint) synchronously, then
    optionally validates the result text through an LLM.
    """

    def __init__(
        self,
        provider: _LLMProvider | None = None,
        model: str | None = None,
        working_dir: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._working_dir = working_dir or os.getcwd()

    async def verify(
        self,
        task: SubTask,
        result: str,
        *,
        run_tests: bool = True,
        run_types: bool = True,
        run_lint: bool = True,
        run_llm: bool = True,
    ) -> VerificationResult:
        """Run all configured checks against a task result.

        Returns a :class:`VerificationResult` aggregating every check.
        """
        checks: list[CheckResult] = []
        suggestions: list[str] = []

        # Automated filesystem checks
        if run_tests:
            checks.append(check_tests_pass(self._working_dir))
        if run_types:
            checks.append(check_type_errors(self._working_dir))
        if run_lint:
            checks.append(check_lint(self._working_dir))

        # LLM review
        if run_llm and self._provider is not None and result:
            llm_check = await self._llm_verify(task, result)
            checks.append(llm_check)
            if not llm_check.passed and llm_check.message:
                suggestions.append(llm_check.message)

        # Aggregate
        all_passed = all(c.passed for c in checks)

        # Collect suggestions from failed checks
        for c in checks:
            if not c.passed and c.message and c.message not in suggestions:
                suggestions.append(f"[{c.name}] {c.message[:200]}")

        return VerificationResult(
            passed=all_passed,
            checks=checks,
            suggestions=suggestions,
        )

    async def _llm_verify(self, task: SubTask, result: str) -> CheckResult:
        """Use the LLM to evaluate the task result."""
        assert self._provider is not None  # noqa: S101

        prompt = build_verification_prompt(task, result)
        try:
            response = await self._provider.chat(
                [{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=800,
                temperature=0.1,
            )
            content = _extract_content(response)
            passed = "PASSED: true" in content.lower()
            # Extract feedback line
            feedback = content
            for line in content.splitlines():
                if line.strip().upper().startswith("FEEDBACK:"):
                    feedback = line.split(":", 1)[1].strip()
                    break
            return CheckResult(name="llm_review", passed=passed, message=feedback)
        except Exception as exc:
            logger.warning("LLM verification failed: %s", exc)
            return CheckResult(
                name="llm_review",
                passed=True,
                message=f"LLM review skipped due to error: {exc}",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_content(response: dict[str, Any] | str) -> str:
    if isinstance(response, str):
        return response
    content = response.get("content", "")
    if not content:
        msg = response.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
    return content
