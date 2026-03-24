"""Tests for the OpenCode CLI subprocess spawner (opencode_spawner)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.swarm.opencode_spawner import (
    _build_opencode_args,
    _extract_files_modified,
    _extract_test_output,
    _extract_tool_actions,
    _find_opencode_binary,
    _is_test_command,
    _parse_opencode_output,
    create_opencode_spawn_fn,
    spawn_opencode_worker,
)
from attocode.integrations.swarm.types import (
    RetryContext,
    SpawnResult,
    SwarmTask,
    SwarmWorkerSpec,
    ToolAction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(**overrides) -> SwarmTask:
    """Create a minimal SwarmTask with sensible defaults."""
    defaults = {"id": "task-1", "description": "Implement feature X"}
    defaults.update(overrides)
    return SwarmTask(**defaults)


def _make_worker(**overrides) -> SwarmWorkerSpec:
    """Create a minimal SwarmWorkerSpec with sensible defaults."""
    defaults = {"name": "worker-1", "model": "o3-mini"}
    defaults.update(overrides)
    return SwarmWorkerSpec(**defaults)


def _make_jsonl(*events: dict) -> str:
    """Build JSONL string from a sequence of event dicts."""
    return "\n".join(json.dumps(e) for e in events)


# ---------------------------------------------------------------------------
# _find_opencode_binary
# ---------------------------------------------------------------------------


class TestFindOpencodeBinary:
    @patch("attocode.integrations.swarm.opencode_spawner.shutil.which")
    def test_returns_path_when_found(self, mock_which):
        mock_which.return_value = "/usr/local/bin/opencode"
        result = _find_opencode_binary()
        assert result == "/usr/local/bin/opencode"
        mock_which.assert_called_once_with("opencode")

    @patch("attocode.integrations.swarm.opencode_spawner.shutil.which")
    def test_returns_none_when_not_found(self, mock_which):
        mock_which.return_value = None
        result = _find_opencode_binary()
        assert result is None
        mock_which.assert_called_once_with("opencode")


# ---------------------------------------------------------------------------
# _is_test_command
# ---------------------------------------------------------------------------


class TestIsTestCommand:
    def test_pytest(self):
        assert _is_test_command("pytest tests/") is True

    def test_npm_test(self):
        assert _is_test_command("npm test") is True

    def test_go_test(self):
        assert _is_test_command("go test ./...") is True

    def test_cargo_test(self):
        assert _is_test_command("cargo test") is True

    def test_jest(self):
        assert _is_test_command("npx jest") is True

    def test_vitest(self):
        assert _is_test_command("vitest run") is True

    def test_mocha(self):
        assert _is_test_command("mocha --reporter spec") is True

    def test_rspec(self):
        assert _is_test_command("bundle exec rspec") is True

    def test_python_m_pytest(self):
        assert _is_test_command("python -m pytest --tb=short") is True

    def test_python_m_unittest(self):
        assert _is_test_command("python -m unittest discover") is True

    def test_make_test(self):
        assert _is_test_command("make test") is True

    def test_not_test_command(self):
        assert _is_test_command("ls -la") is False

    def test_not_test_build(self):
        assert _is_test_command("npm run build") is False

    def test_empty_string(self):
        assert _is_test_command("") is False


# ---------------------------------------------------------------------------
# _extract_tool_actions
# ---------------------------------------------------------------------------


class TestExtractToolActions:
    def test_empty_string(self):
        assert _extract_tool_actions("") == []

    def test_fenced_bash_block(self):
        text = "I ran:\n```bash\npytest tests/\n```\nAll passed."
        actions = _extract_tool_actions(text)
        assert len(actions) >= 1
        assert actions[0].tool_name == "Bash"
        assert "pytest" in actions[0].arguments_summary
        assert actions[0].is_test_execution is True

    def test_dollar_command_pattern(self):
        text = "$ go test ./...\nok  mypackage 0.5s\n"
        actions = _extract_tool_actions(text)
        assert len(actions) >= 1
        assert actions[0].tool_name == "Bash"
        assert "go test" in actions[0].arguments_summary
        assert actions[0].is_test_execution is True

    def test_file_operation_created(self):
        text = "Created file: src/app.py\n"
        actions = _extract_tool_actions(text)
        assert len(actions) >= 1
        assert actions[0].tool_name == "Write"
        assert "src/app.py" in actions[0].arguments_summary

    def test_file_operation_edited(self):
        text = "Edited src/main.ts\n"
        actions = _extract_tool_actions(text)
        assert len(actions) >= 1
        assert actions[0].tool_name == "Edit"

    def test_non_test_command_not_flagged(self):
        text = "```bash\nls -la\n```\n"
        actions = _extract_tool_actions(text)
        assert len(actions) >= 1
        assert actions[0].is_test_execution is False

    def test_deduplicates_commands(self):
        text = "```bash\npytest\n```\n\n$ pytest\nok\n"
        actions = _extract_tool_actions(text)
        bash_actions = [a for a in actions if a.tool_name == "Bash"]
        assert len(bash_actions) == 1

    def test_multiple_blocks(self):
        text = (
            "```bash\npip install flask\n```\n"
            "```bash\npytest tests/\n```\n"
        )
        actions = _extract_tool_actions(text)
        bash_actions = [a for a in actions if a.tool_name == "Bash"]
        assert len(bash_actions) == 2
        assert bash_actions[0].is_test_execution is False
        assert bash_actions[1].is_test_execution is True

    def test_output_summary_truncated_to_1000(self):
        long_output = "x" * 2000
        text = f"```bash\necho hi\n```\n{long_output}\n"
        actions = _extract_tool_actions(text)
        bash_actions = [a for a in actions if a.tool_name == "Bash"]
        if bash_actions:
            assert len(bash_actions[0].output_summary) <= 1000

    def test_arguments_summary_truncated_to_300(self):
        long_cmd = "echo " + "a" * 400
        text = f"```bash\n{long_cmd}\n```\n"
        actions = _extract_tool_actions(text)
        bash_actions = [a for a in actions if a.tool_name == "Bash"]
        if bash_actions:
            assert len(bash_actions[0].arguments_summary) <= 300


# ---------------------------------------------------------------------------
# _extract_test_output
# ---------------------------------------------------------------------------


class TestExtractTestOutput:
    def test_empty_list(self):
        assert _extract_test_output([]) is None

    def test_no_test_actions(self):
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="ls", output_summary="files", is_test_execution=False),
        ]
        assert _extract_test_output(actions) is None

    def test_collects_test_output(self):
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="2 passed", is_test_execution=True),
        ]
        result = _extract_test_output(actions)
        assert result is not None
        assert "2 passed" in result
        assert "pytest" in result

    def test_truncates_long_output(self):
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="x" * 6000, is_test_execution=True),
        ]
        result = _extract_test_output(actions)
        assert result is not None
        assert len(result) <= 5000

    def test_multiple_test_actions_joined(self):
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="2 passed", is_test_execution=True),
            ToolAction(tool_name="Bash", arguments_summary="npm test", output_summary="ok", is_test_execution=True),
        ]
        result = _extract_test_output(actions)
        assert result is not None
        assert "2 passed" in result
        assert "ok" in result

    def test_skips_empty_output_summary(self):
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="", is_test_execution=True),
        ]
        assert _extract_test_output(actions) is None


# ---------------------------------------------------------------------------
# _extract_files_modified
# ---------------------------------------------------------------------------


class TestExtractFilesModified:
    def test_created_file_pattern(self):
        files = _extract_files_modified("Created file: src/utils.py")
        assert "src/utils.py" in files

    def test_wrote_file_pattern(self):
        files = _extract_files_modified("Wrote file: output.txt with results")
        assert "output.txt" in files

    def test_modified_pattern(self):
        files = _extract_files_modified("Modified src/config.py to add defaults")
        assert "src/config.py" in files

    def test_edited_pattern(self):
        files = _extract_files_modified("Edited tests/test_app.py to fix import")
        assert "tests/test_app.py" in files

    def test_updated_pattern(self):
        files = _extract_files_modified("Updated README.md with new instructions")
        assert "README.md" in files

    def test_file_colon_pattern(self):
        files = _extract_files_modified("File: src/parser.py")
        assert "src/parser.py" in files

    def test_path_colon_pattern(self):
        files = _extract_files_modified("Path: lib/helpers.js")
        assert "lib/helpers.js" in files

    def test_multiple_files(self):
        output = (
            "Created file: src/a.py\n"
            "Modified src/b.py\n"
            "Edited src/c.py"
        )
        files = _extract_files_modified(output)
        assert len(files) >= 3
        assert "src/a.py" in files
        assert "src/b.py" in files
        assert "src/c.py" in files

    def test_no_matches_returns_empty_list(self):
        files = _extract_files_modified("Everything looks fine, no changes needed.")
        assert files == []

    def test_deduplicates_paths(self):
        output = "Created file: src/main.py\nModified src/main.py"
        files = _extract_files_modified(output)
        assert files.count("src/main.py") == 1

    def test_strips_surrounding_quotes(self):
        files = _extract_files_modified("Created file: 'src/quoted.py'")
        assert "src/quoted.py" in files


# ---------------------------------------------------------------------------
# _build_opencode_args
# ---------------------------------------------------------------------------


class TestBuildOpencodeArgs:
    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_happy_path_basic(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "You are a coding agent.")

        assert args[0] == "/usr/bin/opencode"
        assert args[1] == "run"
        assert "--format" in args
        assert args[args.index("--format") + 1] == "json"

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_prompt_contains_task_description(self, _mock_find):
        task = _make_task(description="Build the parser")
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "System prompt here.")

        prompt = args[-1]
        assert "Build the parser" in prompt
        assert "System prompt here." in prompt

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_model_from_worker(self, _mock_find):
        task = _make_task()
        worker = _make_worker(model="gpt-4o")
        args = _build_opencode_args(task, worker, "sys")

        assert "--model" in args
        assert args[args.index("--model") + 1] == "gpt-4o"

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_empty_model_omits_flag(self, _mock_find):
        task = _make_task()
        worker = _make_worker(model="")
        args = _build_opencode_args(task, worker, "sys")

        assert "--model" not in args

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_with_target_and_read_files(self, _mock_find):
        task = _make_task(
            target_files=["src/main.py", "src/utils.py"],
            read_files=["README.md"],
        )
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "sys")

        prompt = args[-1]
        assert "Target files: src/main.py, src/utils.py" in prompt
        assert "Reference files: README.md" in prompt

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_with_dependency_context(self, _mock_find):
        task = _make_task(dependency_context="Task A completed: built the schema.")
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "sys")

        prompt = args[-1]
        assert "Context from completed dependencies:" in prompt
        assert "Task A completed: built the schema." in prompt

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_with_retry_context(self, _mock_find):
        rc = RetryContext(
            attempt=1,
            previous_feedback="Tests failed: missing import",
        )
        task = _make_task(retry_context=rc)
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "sys")

        prompt = args[-1]
        assert "retry attempt 2" in prompt
        assert "Tests failed: missing import" in prompt

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value=None)
    def test_raises_file_not_found_when_opencode_missing(self, _mock_find):
        task = _make_task()
        worker = _make_worker()

        with pytest.raises(FileNotFoundError, match="opencode CLI binary not found"):
            _build_opencode_args(task, worker, "sys")

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_no_cwd_in_args(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "sys", working_dir="/tmp/project")

        assert "--cwd" not in args

    @patch("attocode.integrations.swarm.opencode_spawner._find_opencode_binary", return_value="/usr/bin/opencode")
    def test_prompt_is_last_arg(self, _mock_find):
        task = _make_task(description="Do the thing")
        worker = _make_worker()
        args = _build_opencode_args(task, worker, "sys")

        assert "Do the thing" in args[-1]
        assert "sys" in args[-1]


# ---------------------------------------------------------------------------
# _parse_opencode_output
# ---------------------------------------------------------------------------


class TestParseOpencodeOutput:
    def test_empty_string(self):
        result = _parse_opencode_output("")
        assert result.success is False
        assert "Empty output" in result.output

    def test_whitespace_only(self):
        result = _parse_opencode_output("   \n\t  ")
        assert result.success is False

    def test_valid_text_and_step_finish(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "Hello"}},
            {"type": "step_finish", "part": {
                "tokens": {"input": 100, "output": 50, "reasoning": 10},
                "cost": 0.03,
            }},
        )
        result = _parse_opencode_output(raw)
        assert result.success is True
        assert result.output == "Hello"
        assert result.metrics["tokens"] == 160
        assert result.metrics["cost"] == 0.03
        assert result.metrics["input_tokens"] == 100
        assert result.metrics["output_tokens"] == 50
        assert result.metrics["reasoning_tokens"] == 10

    def test_multiple_text_events_concatenated(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "Hello "}},
            {"type": "text", "part": {"text": "world"}},
        )
        result = _parse_opencode_output(raw)
        assert result.success is True
        assert result.output == "Hello world"

    def test_multiple_step_finish_events_accumulated(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "result"}},
            {"type": "step_finish", "part": {"tokens": {"input": 50, "output": 25, "reasoning": 0}, "cost": 0.01}},
            {"type": "step_finish", "part": {"tokens": {"input": 50, "output": 25, "reasoning": 5}, "cost": 0.02}},
        )
        result = _parse_opencode_output(raw)
        assert result.metrics["input_tokens"] == 100
        assert result.metrics["output_tokens"] == 50
        assert result.metrics["reasoning_tokens"] == 5
        assert result.metrics["tokens"] == 155
        assert result.metrics["cost"] == pytest.approx(0.03)

    def test_no_text_output_returns_failure(self):
        raw = _make_jsonl(
            {"type": "step_finish", "part": {"tokens": {"input": 10, "output": 5, "reasoning": 0}, "cost": 0.01}},
        )
        result = _parse_opencode_output(raw)
        assert result.success is False
        assert "No text output" in result.output

    def test_non_json_lines_skipped(self):
        raw = "Loading opencode...\n" + _make_jsonl(
            {"type": "text", "part": {"text": "Hello"}},
        ) + "\nGoodbye."
        result = _parse_opencode_output(raw)
        assert result.success is True
        assert result.output == "Hello"

    def test_non_dict_json_lines_skipped(self):
        raw = "[1,2,3]\n" + _make_jsonl(
            {"type": "text", "part": {"text": "ok"}},
        )
        result = _parse_opencode_output(raw)
        assert result.success is True
        assert result.output == "ok"

    def test_step_start_events_ignored(self):
        raw = _make_jsonl(
            {"type": "step_start", "part": {}},
            {"type": "text", "part": {"text": "Hello"}},
        )
        result = _parse_opencode_output(raw)
        assert result.output == "Hello"
        assert result.metrics["tokens"] == 0

    def test_unknown_event_type_ignored(self):
        raw = _make_jsonl(
            {"type": "debug", "part": {"text": "ignored"}},
            {"type": "text", "part": {"text": "kept"}},
        )
        result = _parse_opencode_output(raw)
        assert result.output == "kept"

    def test_part_not_dict_skipped(self):
        raw = _make_jsonl(
            {"type": "text", "part": "notadict"},
            {"type": "text", "part": {"text": "ok"}},
        )
        result = _parse_opencode_output(raw)
        assert result.success is True
        assert result.output == "ok"

    def test_missing_tokens_key_in_step_finish(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "done"}},
            {"type": "step_finish", "part": {}},
        )
        result = _parse_opencode_output(raw)
        assert result.metrics["tokens"] == 0
        assert result.metrics["input_tokens"] == 0
        assert result.metrics["output_tokens"] == 0

    def test_cost_not_number_ignored(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "done"}},
            {"type": "step_finish", "part": {"cost": "high"}},
        )
        result = _parse_opencode_output(raw)
        assert result.metrics["cost"] == 0.0

    def test_files_modified_extracted(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "Created file: src/main.py"}},
        )
        result = _parse_opencode_output(raw)
        assert result.files_modified is not None
        assert "src/main.py" in result.files_modified

    def test_tool_actions_extracted(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "I ran:\n```bash\npytest tests/\n```\nAll passed."}},
        )
        result = _parse_opencode_output(raw)
        assert result.tool_actions is not None
        assert len(result.tool_actions) >= 1

    def test_test_output_extracted(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "I ran:\n```bash\npytest tests/\n```\n2 passed, 0 failed"}},
        )
        result = _parse_opencode_output(raw)
        assert result.test_output is not None
        assert "pytest" in result.test_output

    def test_no_files_modified_returns_none(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "Analysis complete."}},
        )
        result = _parse_opencode_output(raw)
        assert result.files_modified is None

    def test_no_tool_actions_returns_none(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": "Simple answer."}},
        )
        result = _parse_opencode_output(raw)
        assert result.tool_actions is None

    def test_tool_calls_equals_action_count(self):
        raw = _make_jsonl(
            {"type": "text", "part": {"text": (
                "```bash\nls\n```\n"
                "```bash\npwd\n```\n"
                "```bash\ndate\n```\n"
            )}},
        )
        result = _parse_opencode_output(raw)
        assert result.tool_calls == 3


# ---------------------------------------------------------------------------
# spawn_opencode_worker
# ---------------------------------------------------------------------------


class TestSpawnOpencodeWorker:
    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", side_effect=FileNotFoundError("not found"))
    async def test_binary_not_found_returns_failure(self, _mock_build):
        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")
        assert result.success is False
        assert "not found" in result.output

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "--format", "json", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_successful_spawn(self, mock_exec, _mock_build):
        stdout = _make_jsonl(
            {"type": "text", "part": {"text": "Done!"}},
            {"type": "step_finish", "part": {"tokens": {"input": 100, "output": 50, "reasoning": 0}, "cost": 0.02}},
        )
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")

        assert result.success is True
        assert result.output == "Done!"
        assert result.metrics["tokens"] == 150

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_timeout_kills_process(self, mock_exec, _mock_build):
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = TimeoutError()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys", timeout_ms=1000)

        assert result.success is False
        assert "timed out" in result.output
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_nonzero_exit_empty_stdout(self, mock_exec, _mock_build):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error: segfault")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")

        assert result.success is False
        assert "exited with code 1" in result.output

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_nonzero_exit_with_stdout_still_parses(self, mock_exec, _mock_build):
        stdout = _make_jsonl(
            {"type": "text", "part": {"text": "partial result"}},
        )
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout.encode(), b"warning")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")

        # stdout is not empty, so it should parse rather than shortcutting to error
        assert result.success is True
        assert result.output == "partial result"

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_stderr_preserved_on_result(self, mock_exec, _mock_build):
        stdout = _make_jsonl({"type": "text", "part": {"text": "ok"}})
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout.encode(), b"some warning")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")

        assert result.stderr == "some warning"

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec", side_effect=OSError("exec failed"))
    async def test_exception_in_spawn_returns_failure(self, mock_exec, _mock_build):
        task = _make_task()
        worker = _make_worker()
        result = await spawn_opencode_worker(task, worker, "sys")

        assert result.success is False
        assert "Spawn error" in result.output

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_working_dir_passed_to_subprocess(self, mock_exec, _mock_build):
        stdout = _make_jsonl({"type": "text", "part": {"text": "ok"}})
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        await spawn_opencode_worker(task, worker, "sys", working_dir="/tmp/proj")

        _, kwargs = mock_exec.call_args
        assert kwargs["cwd"] == "/tmp/proj"

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.opencode_spawner._build_opencode_args", return_value=["/usr/bin/opencode", "run", "prompt"])
    @patch("asyncio.create_subprocess_exec")
    async def test_empty_working_dir_passes_none(self, mock_exec, _mock_build):
        stdout = _make_jsonl({"type": "text", "part": {"text": "ok"}})
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        task = _make_task()
        worker = _make_worker()
        await spawn_opencode_worker(task, worker, "sys", working_dir="")

        _, kwargs = mock_exec.call_args
        assert kwargs["cwd"] is None


# ---------------------------------------------------------------------------
# create_opencode_spawn_fn
# ---------------------------------------------------------------------------


class TestCreateOpencodeSpawnFn:
    def test_returns_callable(self):
        fn = create_opencode_spawn_fn(working_dir="/tmp")
        assert callable(fn)

    def test_returned_fn_is_async(self):
        fn = create_opencode_spawn_fn()
        assert asyncio.iscoroutinefunction(fn)

    @patch("attocode.integrations.swarm.opencode_spawner.spawn_opencode_worker")
    @pytest.mark.asyncio
    async def test_spawn_fn_delegates_to_spawn_opencode_worker(self, mock_spawn):
        mock_spawn.return_value = SpawnResult(success=True, output="ok")

        fn = create_opencode_spawn_fn(working_dir="/projects/demo")
        task = _make_task()
        worker = _make_worker()

        result = await fn(task, worker, "system prompt")

        assert result.success is True
        mock_spawn.assert_called_once()
        call_kwargs = mock_spawn.call_args
        assert call_kwargs.kwargs["working_dir"] == "/projects/demo"

    @patch("attocode.integrations.swarm.opencode_spawner.spawn_opencode_worker")
    @pytest.mark.asyncio
    async def test_spawn_fn_passes_max_tokens(self, mock_spawn):
        mock_spawn.return_value = SpawnResult(success=True, output="ok")

        fn = create_opencode_spawn_fn()
        task = _make_task()
        worker = _make_worker()

        await fn(task, worker, "sys", max_tokens=100_000)

        call_kwargs = mock_spawn.call_args
        assert call_kwargs.kwargs["max_tokens"] == 100_000

    @patch("attocode.integrations.swarm.opencode_spawner.spawn_opencode_worker")
    @pytest.mark.asyncio
    async def test_spawn_fn_accepts_extra_kwargs(self, mock_spawn):
        mock_spawn.return_value = SpawnResult(success=True, output="ok")

        fn = create_opencode_spawn_fn()
        task = _make_task()
        worker = _make_worker()

        # Should not raise even with extra kwargs
        await fn(task, worker, "sys", extra_kwarg="ignored")
        mock_spawn.assert_called_once()
