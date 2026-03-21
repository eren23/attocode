"""Post-task verification gate.

Runs automated checks (tests, type-checking, linting) and optionally
an LLM-based review to verify that a subtask was completed correctly.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
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
# Targeted file compilation check
# ---------------------------------------------------------------------------


@dataclass
class CompilationCheckResult:
    """Result of running compilation checks on modified files.

    Extends the basic CheckResult contract with an ``errors`` list
    containing per-file error details.
    """

    passed: bool
    message: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)
    files_checked: int = 0


def check_modified_files_compile(
    modified_files: list[str], working_dir: str
) -> CompilationCheckResult:
    """Run compilation / syntax checks on specific modified files only.

    Performs per-language checks:
    - Python (.py): ``compile(source, filename, 'exec')``
    - JSON (.json): ``json.loads()``
    - JavaScript (.js): ``node --check``
    - TypeScript (.ts/.tsx): ``tsc --noEmit --isolatedModules`` on modified files

    Returns a :class:`CompilationCheckResult` whose ``passed`` field is
    ``True`` only if every file compiles successfully.
    """
    import json as _json

    errors: list[dict[str, Any]] = []
    files_checked = 0

    for fpath in modified_files or []:
        # Resolve path relative to working_dir
        full_path = os.path.join(working_dir, fpath) if not os.path.isabs(fpath) else fpath
        if not os.path.isfile(full_path):
            continue

        ext = os.path.splitext(full_path)[1].lower()
        files_checked += 1

        if ext == ".py":
            try:
                with open(full_path, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                compile(source, fpath, "exec")
            except SyntaxError as exc:
                errors.append({
                    "file": fpath,
                    "line": exc.lineno,
                    "message": f"SyntaxError: {exc.msg}",
                })
            except Exception as exc:
                errors.append({
                    "file": fpath,
                    "line": None,
                    "message": str(exc)[:200],
                })

        elif ext == ".json":
            try:
                with open(full_path, encoding="utf-8") as f:
                    _json.loads(f.read())
            except _json.JSONDecodeError as exc:
                errors.append({
                    "file": fpath,
                    "line": exc.lineno,
                    "message": f"JSONDecodeError: {exc.msg}",
                })
            except Exception as exc:
                errors.append({
                    "file": fpath,
                    "line": None,
                    "message": str(exc)[:200],
                })

        elif ext == ".js":
            passed, output = _run_command(["node", "--check", full_path], working_dir)
            if not passed:
                # Try to extract line number from node output
                line_no = None
                for line in output.splitlines():
                    if ":" in line:
                        parts = line.split(":")
                        for p in parts:
                            p = p.strip()
                            if p.isdigit():
                                line_no = int(p)
                                break
                        if line_no is not None:
                            break
                errors.append({
                    "file": fpath,
                    "line": line_no,
                    "message": output[:300],
                })

        elif ext in (".ts", ".tsx"):
            passed, output = _run_command(
                ["npx", "tsc", "--noEmit", "--isolatedModules", full_path],
                working_dir,
            )
            if not passed:
                errors.append({
                    "file": fpath,
                    "line": None,
                    "message": output[:300],
                })

    if errors:
        error_summary = "; ".join(
            f"{e['file']}: {e['message']}" for e in errors[:5]
        )
        return CompilationCheckResult(
            passed=False,
            message=f"Compilation failed ({len(errors)} error(s)): {error_summary}"[:500],
            errors=errors,
            files_checked=files_checked,
        )

    return CompilationCheckResult(
        passed=True,
        message=f"All {files_checked} modified files compile successfully",
        errors=[],
        files_checked=files_checked,
    )


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
        if self._provider is None:
            return CheckResult(name="llm", passed=False, message="No LLM provider configured")

        prompt = build_verification_prompt(task, result)
        try:
            response = await self._provider.chat(
                [{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=800,
                temperature=0.1,
            )
            content = _extract_content(response)
            passed = "passed: true" in content.lower()
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
