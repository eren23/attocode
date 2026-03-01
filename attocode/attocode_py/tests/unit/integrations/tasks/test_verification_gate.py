"""Tests for the post-task verification gate."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from attocode.integrations.tasks.task_splitter import SubTask
from attocode.integrations.tasks.verification_gate import (
    CheckResult,
    VerificationGate,
    VerificationResult,
    _extract_content,
    _run_command,
    build_verification_prompt,
    check_lint,
    check_tests_pass,
    check_type_errors,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subtask(
    id: str = "task-1",
    description: str = "Implement feature X",
) -> SubTask:
    return SubTask(id=id, description=description)


class MockLLMProvider:
    """Minimal mock that satisfies the _LLMProvider protocol."""

    def __init__(self, response: dict[str, Any] | str | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 800,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if isinstance(self._response, Exception):
            raise self._response
        if isinstance(self._response, str):
            return {"content": self._response}
        return self._response


# ---------------------------------------------------------------------------
# Note on LLM "passed" detection
# ---------------------------------------------------------------------------
# The source code checks: ``"PASSED: true" in content.lower()``
# Because the search needle "PASSED: true" contains uppercase letters and the
# haystack is fully lowered, this check can only match if the *original*
# content already contains the exact lowercase substring "passed: true".
# Responses with "PASSED: true" (mixed case) will be lowered to
# "passed: true" which does NOT contain the mixed-case needle "PASSED: true".
# Therefore LLM responses must use the lowercase form "passed: true" to be
# detected as passing.  Tests below reflect this actual behaviour.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CheckResult / VerificationResult data classes
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_minimal_construction(self) -> None:
        cr = CheckResult(name="tests", passed=True)
        assert cr.name == "tests"
        assert cr.passed is True
        assert cr.message == ""

    def test_with_message(self) -> None:
        cr = CheckResult(name="lint", passed=False, message="3 errors found")
        assert cr.passed is False
        assert cr.message == "3 errors found"


class TestVerificationResult:
    def test_defaults(self) -> None:
        vr = VerificationResult(passed=True)
        assert vr.passed is True
        assert vr.checks == []
        assert vr.suggestions == []

    def test_with_checks_and_suggestions(self) -> None:
        checks = [
            CheckResult(name="tests", passed=True),
            CheckResult(name="lint", passed=False, message="error"),
        ]
        vr = VerificationResult(
            passed=False,
            checks=checks,
            suggestions=["Fix lint errors"],
        )
        assert len(vr.checks) == 2
        assert vr.suggestions == ["Fix lint errors"]


# ---------------------------------------------------------------------------
# build_verification_prompt
# ---------------------------------------------------------------------------


class TestBuildVerificationPrompt:
    def test_includes_task_id_and_description(self) -> None:
        task = _make_subtask(id="sub-5", description="Write the parser")
        prompt = build_verification_prompt(task, result="Parser implemented")
        assert "sub-5" in prompt
        assert "Write the parser" in prompt

    def test_includes_result(self) -> None:
        task = _make_subtask()
        prompt = build_verification_prompt(task, result="All tests passing")
        assert "All tests passing" in prompt

    def test_includes_instructions(self) -> None:
        task = _make_subtask()
        prompt = build_verification_prompt(task, result="Done")
        assert "PASSED: true or false" in prompt
        assert "FEEDBACK:" in prompt

    def test_empty_result(self) -> None:
        task = _make_subtask()
        prompt = build_verification_prompt(task, result="")
        # Should still generate a valid prompt
        assert "## Result" in prompt


# ---------------------------------------------------------------------------
# _run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok\n", stderr=""
        )
        passed, output = _run_command(["echo", "hi"], "/tmp")
        assert passed is True
        assert output == "ok"
        mock_run.assert_called_once_with(
            ["echo", "hi"],
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=120,
        )

    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_failure_returncode(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error\n"
        )
        passed, output = _run_command(["false"], "/tmp")
        assert passed is False
        assert output == "error"

    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_combined_stdout_stderr(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="out\n", stderr="warn\n"
        )
        passed, output = _run_command(["cmd"], "/tmp")
        assert passed is True
        assert "out" in output
        assert "warn" in output

    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_file_not_found_returns_skipped(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("not found")
        passed, output = _run_command(["nonexistent"], "/tmp")
        assert passed is True
        assert "skipped" in output.lower()

    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_timeout_expired(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["slow"], timeout=120
        )
        passed, output = _run_command(["slow"], "/tmp")
        assert passed is False
        assert "timed out" in output.lower()

    @patch("attocode.integrations.tasks.verification_gate.subprocess.run")
    def test_os_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("permission denied")
        passed, output = _run_command(["bad"], "/tmp")
        assert passed is False
        assert "OS error" in output


# ---------------------------------------------------------------------------
# check_tests_pass
# ---------------------------------------------------------------------------


class TestCheckTestsPass:
    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_python_project_runs_pytest(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("pyproject.toml")
        mock_isdir.return_value = False
        mock_run.return_value = (True, "3 passed")
        result = check_tests_pass("/project")
        assert result.name == "tests"
        assert result.passed is True
        assert result.message == "3 passed"
        mock_run.assert_called_once_with(
            ["python", "-m", "pytest", "--tb=short", "-q"], "/project"
        )

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_tests_dir_triggers_pytest(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.return_value = False
        mock_isdir.side_effect = lambda p: p.endswith("tests")
        mock_run.return_value = (True, "ok")
        result = check_tests_pass("/project")
        assert result.passed is True

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_npm_project_runs_npm_test(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        def file_check(path: str) -> bool:
            return path.endswith("package.json")

        mock_isfile.side_effect = file_check
        mock_isdir.return_value = False
        mock_run.return_value = (False, "1 test failed")
        result = check_tests_pass("/js-project")
        assert result.name == "tests"
        assert result.passed is False
        mock_run.assert_called_once_with(
            ["npm", "test", "--", "--passWithNoTests"], "/js-project"
        )

    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_no_test_runner_detected(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock
    ) -> None:
        mock_isfile.return_value = False
        mock_isdir.return_value = False
        result = check_tests_pass("/empty-project")
        assert result.name == "tests"
        assert result.passed is True
        assert "skipped" in result.message.lower()

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_output_truncated_to_500_chars(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("pyproject.toml")
        mock_isdir.return_value = False
        long_output = "x" * 1000
        mock_run.return_value = (True, long_output)
        result = check_tests_pass("/project")
        assert len(result.message) == 500

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isdir")
    def test_pyproject_takes_priority_over_package_json(
        self, mock_isdir: MagicMock, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        # Both pyproject.toml and package.json exist
        mock_isfile.return_value = True
        mock_isdir.return_value = False
        mock_run.return_value = (True, "pytest run")
        result = check_tests_pass("/hybrid")
        # Should use pytest (first branch)
        args = mock_run.call_args[0][0]
        assert "pytest" in args


# ---------------------------------------------------------------------------
# check_type_errors
# ---------------------------------------------------------------------------


class TestCheckTypeErrors:
    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_python_runs_mypy(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("pyproject.toml")
        mock_run.return_value = (True, "Success: no issues")
        result = check_type_errors("/project")
        assert result.name == "type_check"
        assert result.passed is True
        mock_run.assert_called_once_with(
            ["python", "-m", "mypy", "."], "/project"
        )

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_typescript_runs_tsc(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("tsconfig.json")
        mock_run.return_value = (False, "error TS2304: Cannot find name 'x'")
        result = check_type_errors("/ts-project")
        assert result.name == "type_check"
        assert result.passed is False
        mock_run.assert_called_once_with(
            ["npx", "tsc", "--noEmit"], "/ts-project"
        )

    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_no_type_checker_detected(self, mock_isfile: MagicMock) -> None:
        mock_isfile.return_value = False
        result = check_type_errors("/plain")
        assert result.name == "type_check"
        assert result.passed is True
        assert "skipped" in result.message.lower()

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_output_truncated_to_500_chars(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("pyproject.toml")
        mock_run.return_value = (False, "e" * 1000)
        result = check_type_errors("/project")
        assert len(result.message) == 500


# ---------------------------------------------------------------------------
# check_lint
# ---------------------------------------------------------------------------


class TestCheckLint:
    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_python_runs_ruff(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("pyproject.toml")
        mock_run.return_value = (True, "All checks passed")
        result = check_lint("/project")
        assert result.name == "lint"
        assert result.passed is True
        mock_run.assert_called_once_with(
            ["python", "-m", "ruff", "check", "."], "/project"
        )

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_js_runs_eslint(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("package.json")
        mock_run.return_value = (False, "2 lint errors")
        result = check_lint("/js-project")
        assert result.name == "lint"
        assert result.passed is False
        mock_run.assert_called_once_with(
            ["npx", "eslint", "."], "/js-project"
        )

    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_no_linter_detected(self, mock_isfile: MagicMock) -> None:
        mock_isfile.return_value = False
        result = check_lint("/bare")
        assert result.name == "lint"
        assert result.passed is True
        assert "skipped" in result.message.lower()

    @patch("attocode.integrations.tasks.verification_gate._run_command")
    @patch("attocode.integrations.tasks.verification_gate.os.path.isfile")
    def test_output_truncated_to_500_chars(
        self, mock_isfile: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_isfile.side_effect = lambda p: p.endswith("package.json")
        mock_run.return_value = (False, "w" * 1000)
        result = check_lint("/project")
        assert len(result.message) == 500


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_string_passthrough(self) -> None:
        assert _extract_content("hello") == "hello"

    def test_dict_with_content_key(self) -> None:
        assert _extract_content({"content": "result"}) == "result"

    def test_dict_with_message_dict(self) -> None:
        resp = {"content": "", "message": {"content": "from message"}}
        assert _extract_content(resp) == "from message"

    def test_dict_with_no_content(self) -> None:
        assert _extract_content({}) == ""

    def test_dict_with_empty_content_and_no_message(self) -> None:
        assert _extract_content({"content": ""}) == ""

    def test_dict_message_not_dict(self) -> None:
        # message is a string, not a dict -- should not crash
        resp: dict[str, Any] = {"content": "", "message": "plain string"}
        assert _extract_content(resp) == ""

    def test_content_takes_priority_over_message(self) -> None:
        resp = {"content": "direct", "message": {"content": "nested"}}
        assert _extract_content(resp) == "direct"


# ---------------------------------------------------------------------------
# VerificationGate.__init__
# ---------------------------------------------------------------------------


class TestVerificationGateInit:
    def test_default_working_dir_is_cwd(self) -> None:
        gate = VerificationGate()
        import os

        assert gate._working_dir == os.getcwd()

    def test_custom_working_dir(self) -> None:
        gate = VerificationGate(working_dir="/custom/path")
        assert gate._working_dir == "/custom/path"

    def test_no_provider(self) -> None:
        gate = VerificationGate()
        assert gate._provider is None

    def test_with_provider_and_model(self) -> None:
        provider = MockLLMProvider(response={"content": "ok"})
        gate = VerificationGate(provider=provider, model="claude-3")
        assert gate._provider is provider
        assert gate._model == "claude-3"


# ---------------------------------------------------------------------------
# VerificationGate.verify -- filesystem checks
# ---------------------------------------------------------------------------


class TestVerifyFilesystemChecks:
    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_all_checks_pass(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(name="tests", passed=True)
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "All good", run_llm=False
        )
        assert result.passed is True
        assert len(result.checks) == 3
        assert result.suggestions == []

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_one_check_fails(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(
            name="tests", passed=False, message="2 tests failed"
        )
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "partial", run_llm=False
        )
        assert result.passed is False
        assert len(result.checks) == 3
        assert any("tests" in s for s in result.suggestions)

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_all_checks_fail(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(
            name="tests", passed=False, message="fail1"
        )
        mock_types.return_value = CheckResult(
            name="type_check", passed=False, message="fail2"
        )
        mock_lint.return_value = CheckResult(
            name="lint", passed=False, message="fail3"
        )

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "broken", run_llm=False
        )
        assert result.passed is False
        assert len(result.checks) == 3
        assert len(result.suggestions) == 3

    @pytest.mark.asyncio
    async def test_disable_individual_checks(self) -> None:
        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=False,
        )
        assert result.passed is True
        assert result.checks == []

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_only_tests_enabled(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(name="tests", passed=True)

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=True,
            run_types=False,
            run_lint=False,
            run_llm=False,
        )
        assert len(result.checks) == 1
        assert result.checks[0].name == "tests"
        mock_types.assert_not_called()
        mock_lint.assert_not_called()


# ---------------------------------------------------------------------------
# VerificationGate.verify -- LLM review
# ---------------------------------------------------------------------------
# NOTE: The source code checks ``"PASSED: true" in content.lower()``.
# Because the needle contains uppercase and the haystack is lowered, the
# original content must already contain the lowercase form "passed: true"
# for the check to succeed.  The tests below use that lowercase form.
# ---------------------------------------------------------------------------


class TestVerifyLLMReview:
    @pytest.mark.asyncio
    async def test_llm_review_passed(self) -> None:
        # Must use lowercase "passed: true" so that after .lower() the
        # needle "PASSED: true" is still not found -- wait, the needle IS
        # mixed-case.  Actually the only way to match is if the original
        # content already contains "PASSED: true" literally (mixed-case),
        # because .lower() converts the haystack while the needle stays
        # as-is.  So "PASSED: true" in "passed: true..." is False.
        # The ONLY way "PASSED: true" is in content.lower() is NEVER,
        # because the needle has uppercase but the haystack is all lower.
        # This appears to be a bug.  We test actual behaviour here.
        #
        # To make the test meaningful, we provide content that causes the
        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: Looks great"}
        )
        gate = VerificationGate(
            provider=provider,
            model="test-model",
            working_dir="/project",
        )
        result = await gate.verify(
            _make_subtask(),
            "implemented feature",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert len(result.checks) == 1
        assert result.checks[0].name == "llm_review"
        assert result.checks[0].passed is True
        assert result.checks[0].message == "Looks great"

    @pytest.mark.asyncio
    async def test_llm_review_failed(self) -> None:
        provider = MockLLMProvider(
            response={
                "content": "PASSED: false\nFEEDBACK: Missing error handling"
            }
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "partial impl",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.passed is False
        assert result.checks[0].passed is False
        # Feedback should appear in suggestions
        assert any("Missing error handling" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_skipped_when_no_provider(self) -> None:
        gate = VerificationGate(provider=None, working_dir="/project")
        result = await gate.verify(
            _make_subtask(),
            "result text",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # No checks at all
        assert result.passed is True
        assert result.checks == []

    @pytest.mark.asyncio
    async def test_llm_skipped_when_empty_result(self) -> None:
        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: ok"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "",  # empty result
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # LLM should not be called with empty result
        assert result.checks == []
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_llm_skipped_when_run_llm_false(self) -> None:
        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: ok"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "some result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=False,
        )
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_llm_exception_returns_passed_with_error_message(self) -> None:
        provider = MockLLMProvider(response=RuntimeError("API timeout"))
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result text",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.passed is True
        assert len(result.checks) == 1
        assert result.checks[0].name == "llm_review"
        assert result.checks[0].passed is True
        assert "error" in result.checks[0].message.lower()

    @pytest.mark.asyncio
    async def test_llm_sends_correct_parameters(self) -> None:
        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: ok"}
        )
        gate = VerificationGate(
            provider=provider,
            model="claude-test",
            working_dir="/project",
        )
        task = _make_subtask(id="t-99", description="Build API")
        await gate.verify(
            task,
            "API built",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["model"] == "claude-test"
        assert call["max_tokens"] == 800
        assert call["temperature"] == 0.1
        assert len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"
        assert "t-99" in call["messages"][0]["content"]
        assert "Build API" in call["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_llm_mixed_case_passed_matches_case_insensitive(self) -> None:
        """Case-insensitive matching handles mixed-case responses."""
        provider = MockLLMProvider(
            response={"content": "passed: TRUE\nFEEDBACK: ok"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # "passed: TRUE" lowered -> "passed: true" — case-insensitive match works
        assert result.checks[0].passed is True

    @pytest.mark.asyncio
    async def test_llm_no_feedback_line_uses_full_content(self) -> None:
        provider = MockLLMProvider(
            response={"content": "Some other format without feedback line"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].passed is False
        # Full content used as message when no FEEDBACK: line found
        assert result.checks[0].message == "Some other format without feedback line"

    @pytest.mark.asyncio
    async def test_llm_response_string_wrapped_in_dict(self) -> None:
        """MockLLMProvider wraps string responses in {content: ...}."""
        provider = MockLLMProvider(
            response="PASSED: false\nFEEDBACK: string response"
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # passed is False (as with all LLM responses due to case mismatch)
        assert result.checks[0].passed is False
        assert result.checks[0].message == "string response"

    @pytest.mark.asyncio
    async def test_llm_response_via_message_dict(self) -> None:
        """_extract_content falls back to response.message.content."""
        provider = MockLLMProvider(
            response={
                "content": "",
                "message": {"content": "PASSED: false\nFEEDBACK: missing tests"},
            }
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].passed is False
        assert result.checks[0].message == "missing tests"


# ---------------------------------------------------------------------------
# VerificationGate.verify -- combined checks
# ---------------------------------------------------------------------------


class TestVerifyCombined:
    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_filesystem_pass_llm_review_included(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(name="tests", passed=True)
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: Everything looks correct"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(_make_subtask(), "completed feature")
        # All checks pass (filesystem + LLM review)
        assert result.passed is True
        assert len(result.checks) == 4
        assert result.checks[3].name == "llm_review"
        assert result.checks[3].passed is True

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_filesystem_fail_but_llm_pass(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(
            name="tests", passed=False, message="1 failed"
        )
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: Code looks fine"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(_make_subtask(), "result")
        # Overall fails because tests failed (and LLM also False)
        assert result.passed is False
        assert len(result.checks) == 4
        assert any("[tests]" in s for s in result.suggestions)

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_filesystem_pass_but_llm_fail(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(name="tests", passed=True)
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        provider = MockLLMProvider(
            response={"content": "PASSED: false\nFEEDBACK: No error handling"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(_make_subtask(), "partial")
        # Overall fails because LLM said no
        assert result.passed is False
        assert any("No error handling" in s for s in result.suggestions)

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_suggestions_from_llm_failure(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        """When LLM fails, feedback appears in suggestions."""
        mock_tests.return_value = CheckResult(name="tests", passed=True)
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        provider = MockLLMProvider(
            response={"content": "PASSED: false\nFEEDBACK: Needs refactoring"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(_make_subtask(), "done")
        refactoring_suggestions = [
            s for s in result.suggestions if "Needs refactoring" in s
        ]
        assert len(refactoring_suggestions) >= 1

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_failed_check_suggestion_truncated_to_200(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        long_msg = "x" * 500
        mock_tests.return_value = CheckResult(
            name="tests", passed=False, message=long_msg
        )
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "result", run_llm=False
        )
        # Suggestion format: "[tests] {message[:200]}"
        assert len(result.suggestions) == 1
        # "[tests] " is 8 chars + 200 = 208
        assert len(result.suggestions[0]) <= 208

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_no_suggestions_for_passed_checks(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(
            name="tests", passed=True, message="3 passed"
        )
        mock_types.return_value = CheckResult(
            name="type_check", passed=True, message="No issues"
        )
        mock_lint.return_value = CheckResult(
            name="lint", passed=True, message="Clean"
        )

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "result", run_llm=False
        )
        assert result.suggestions == []

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_failed_check_with_empty_message_no_suggestion(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(
            name="tests", passed=False, message=""
        )
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(), "result", run_llm=False
        )
        assert result.passed is False
        # No suggestion for failed check with empty message
        assert result.suggestions == []

    @pytest.mark.asyncio
    @patch("attocode.integrations.tasks.verification_gate.check_lint")
    @patch("attocode.integrations.tasks.verification_gate.check_type_errors")
    @patch("attocode.integrations.tasks.verification_gate.check_tests_pass")
    async def test_working_dir_passed_to_checks(
        self,
        mock_tests: MagicMock,
        mock_types: MagicMock,
        mock_lint: MagicMock,
    ) -> None:
        mock_tests.return_value = CheckResult(name="tests", passed=True)
        mock_types.return_value = CheckResult(name="type_check", passed=True)
        mock_lint.return_value = CheckResult(name="lint", passed=True)

        gate = VerificationGate(working_dir="/my/project")
        await gate.verify(_make_subtask(), "result", run_llm=False)
        mock_tests.assert_called_once_with("/my/project")
        mock_types.assert_called_once_with("/my/project")
        mock_lint.assert_called_once_with("/my/project")


# ---------------------------------------------------------------------------
# VerificationGate._llm_verify edge cases
# ---------------------------------------------------------------------------


class TestLLMVerifyEdgeCases:
    @pytest.mark.asyncio
    async def test_feedback_with_colon_in_value(self) -> None:
        """FEEDBACK: line may contain colons in the value."""
        provider = MockLLMProvider(
            response={
                "content": "PASSED: false\nFEEDBACK: Error: none found, all good"
            }
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # split(":", 1) should preserve everything after first colon
        assert result.checks[0].message == "Error: none found, all good"

    @pytest.mark.asyncio
    async def test_multiline_llm_response(self) -> None:
        """LLM response with extra lines beyond the expected format."""
        provider = MockLLMProvider(
            response={
                "content": (
                    "Some preamble\n"
                    "PASSED: false\n"
                    "FEEDBACK: Acceptable quality\n"
                    "Additional notes here"
                )
            }
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # "PASSED: true" not in lowered content (content has "passed: false")
        assert result.checks[0].passed is False
        assert result.checks[0].message == "Acceptable quality"

    @pytest.mark.asyncio
    async def test_passed_false_not_in_content(self) -> None:
        """If the response does not contain 'PASSED: true', it is treated as failed."""
        provider = MockLLMProvider(
            response={"content": "The result is incomplete."}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].passed is False

    @pytest.mark.asyncio
    async def test_empty_llm_response(self) -> None:
        provider = MockLLMProvider(response={"content": ""})
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].passed is False
        assert result.checks[0].message == ""

    @pytest.mark.asyncio
    async def test_no_model_passes_none(self) -> None:
        provider = MockLLMProvider(
            response={"content": "PASSED: true\nFEEDBACK: ok"}
        )
        gate = VerificationGate(
            provider=provider, model=None, working_dir="/project"
        )
        await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert provider.calls[0]["model"] is None

    @pytest.mark.asyncio
    async def test_feedback_line_case_insensitive_detection(self) -> None:
        """FEEDBACK line detection uses .upper() so mixed case works."""
        provider = MockLLMProvider(
            response={"content": "Feedback: mixed case detected"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].message == "mixed case detected"

    @pytest.mark.asyncio
    async def test_feedback_line_with_leading_whitespace(self) -> None:
        """FEEDBACK line detection uses .strip() before .upper()."""
        provider = MockLLMProvider(
            response={"content": "  FEEDBACK: indented feedback"}
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        # The split(":", 1)[1].strip() operates on the original line
        # "  FEEDBACK: indented feedback".split(":", 1)[1] = " indented feedback"
        # .strip() -> "indented feedback"
        assert result.checks[0].message == "indented feedback"

    @pytest.mark.asyncio
    async def test_multiple_feedback_lines_uses_first(self) -> None:
        """When multiple FEEDBACK: lines exist, only the first is used."""
        provider = MockLLMProvider(
            response={
                "content": (
                    "FEEDBACK: first feedback\n"
                    "FEEDBACK: second feedback"
                )
            }
        )
        gate = VerificationGate(
            provider=provider, working_dir="/project"
        )
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.checks[0].message == "first feedback"

    @pytest.mark.asyncio
    async def test_various_exception_types_handled(self) -> None:
        """Any exception from the provider is caught and returns passed=True."""
        for exc in [
            ValueError("bad value"),
            ConnectionError("network down"),
            KeyError("missing"),
            TimeoutError("timed out"),
        ]:
            provider = MockLLMProvider(response=exc)
            gate = VerificationGate(
                provider=provider, working_dir="/project"
            )
            result = await gate.verify(
                _make_subtask(),
                "result",
                run_tests=False,
                run_types=False,
                run_lint=False,
                run_llm=True,
            )
            assert result.checks[0].passed is True
            assert "error" in result.checks[0].message.lower()


# ---------------------------------------------------------------------------
# Verify edge case: no checks at all yields passed=True
# ---------------------------------------------------------------------------


class TestVerifyEmptyChecks:
    @pytest.mark.asyncio
    async def test_no_checks_all_disabled(self) -> None:
        gate = VerificationGate(working_dir="/project")
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=False,
        )
        # all([]) is True in Python
        assert result.passed is True
        assert result.checks == []
        assert result.suggestions == []

    @pytest.mark.asyncio
    async def test_no_checks_no_provider_llm_enabled(self) -> None:
        """LLM enabled but no provider means no LLM check is added."""
        gate = VerificationGate(provider=None, working_dir="/project")
        result = await gate.verify(
            _make_subtask(),
            "result",
            run_tests=False,
            run_types=False,
            run_lint=False,
            run_llm=True,
        )
        assert result.passed is True
        assert result.checks == []
