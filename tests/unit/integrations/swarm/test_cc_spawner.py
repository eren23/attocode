"""Tests for the Claude Code CLI subprocess spawner (cc_spawner)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from attocode.integrations.swarm.cc_spawner import (
    _build_cli_args,
    _extract_files_modified,
    _extract_test_output,
    _extract_tool_actions,
    _find_claude_binary,
    _is_test_command,
    _parse_cc_output,
    create_cc_spawn_fn,
)
from attocode.integrations.swarm.types import (
    RetryContext,
    SpawnResult,
    SwarmTask,
    SwarmWorkerSpec,
    WorkerCapability,
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
    defaults = {
        "name": "worker-1",
        "model": "claude-sonnet-4-20250514",
    }
    defaults.update(overrides)
    return SwarmWorkerSpec(**defaults)


# ---------------------------------------------------------------------------
# _find_claude_binary
# ---------------------------------------------------------------------------


class TestFindClaudeBinary:
    @patch("attocode.integrations.swarm.cc_spawner.shutil.which")
    def test_returns_path_when_found(self, mock_which):
        mock_which.return_value = "/usr/local/bin/claude"
        result = _find_claude_binary()
        assert result == "/usr/local/bin/claude"
        mock_which.assert_called_once_with("claude")

    @patch("attocode.integrations.swarm.cc_spawner.shutil.which")
    def test_returns_none_when_not_found(self, mock_which):
        mock_which.return_value = None
        result = _find_claude_binary()
        assert result is None
        mock_which.assert_called_once_with("claude")


# ---------------------------------------------------------------------------
# _build_cli_args
# ---------------------------------------------------------------------------


class TestBuildCliArgs:
    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_happy_path_basic(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_cli_args(task, worker, "You are a coding agent.")

        assert args[0] == "/usr/bin/claude"
        assert "-p" in args
        assert "--output-format" in args
        assert args[args.index("--output-format") + 1] == "json"
        assert "--max-turns" in args
        assert "--dangerously-skip-permissions" in args

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_prompt_contains_task_description(self, _mock_find):
        task = _make_task(description="Build the parser")
        worker = _make_worker()
        args = _build_cli_args(task, worker, "System prompt here.")

        prompt_idx = args.index("-p") + 1
        prompt = args[prompt_idx]
        assert "Build the parser" in prompt
        assert "System prompt here." in prompt

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_with_working_dir(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys", working_dir="/tmp/project")

        assert "--cwd" in args
        assert args[args.index("--cwd") + 1] == "/tmp/project"

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_without_working_dir(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys", working_dir="")

        assert "--cwd" not in args

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_model_override_from_worker(self, _mock_find):
        task = _make_task()
        worker = _make_worker(model="gpt-4o")
        args = _build_cli_args(task, worker, "sys")

        assert "--model" in args
        assert args[args.index("--model") + 1] == "gpt-4o"

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_with_target_and_read_files(self, _mock_find):
        task = _make_task(
            target_files=["src/main.py", "src/utils.py"],
            read_files=["README.md"],
        )
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys")

        prompt_idx = args.index("-p") + 1
        prompt = args[prompt_idx]
        assert "Target files: src/main.py, src/utils.py" in prompt
        assert "Reference files: README.md" in prompt

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_with_dependency_context(self, _mock_find):
        task = _make_task(dependency_context="Task A completed: built the schema.")
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys")

        prompt_idx = args.index("-p") + 1
        prompt = args[prompt_idx]
        assert "Context from completed dependencies:" in prompt
        assert "Task A completed: built the schema." in prompt

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_with_retry_context(self, _mock_find):
        rc = RetryContext(
            attempt=1,
            previous_feedback="Tests failed: missing import",
        )
        task = _make_task(retry_context=rc)
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys")

        prompt_idx = args.index("-p") + 1
        prompt = args[prompt_idx]
        assert "retry attempt 2" in prompt
        assert "Tests failed: missing import" in prompt

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_max_turns_uses_max_iterations(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys", max_iterations=25)

        idx = args.index("--max-turns") + 1
        assert args[idx] == "25"

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_max_turns_minimum_is_5(self, _mock_find):
        task = _make_task()
        worker = _make_worker()
        args = _build_cli_args(task, worker, "sys", max_iterations=2)

        idx = args.index("--max-turns") + 1
        assert args[idx] == "5"

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_allowed_tools_from_worker(self, _mock_find):
        task = _make_task()
        worker = _make_worker(allowed_tools=["Read", "Bash"])
        args = _build_cli_args(task, worker, "sys")

        assert "--allowedTools" in args
        assert args[args.index("--allowedTools") + 1] == "Read,Bash"

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value="/usr/bin/claude")
    def test_default_allowed_tools_when_none(self, _mock_find):
        task = _make_task()
        worker = _make_worker(allowed_tools=None)
        args = _build_cli_args(task, worker, "sys")

        assert "--allowedTools" in args
        tools_str = args[args.index("--allowedTools") + 1]
        assert "Read" in tools_str
        assert "Write" in tools_str
        assert "Bash" in tools_str

    @patch("attocode.integrations.swarm.cc_spawner._find_claude_binary", return_value=None)
    def test_raises_file_not_found_when_claude_missing(self, _mock_find):
        task = _make_task()
        worker = _make_worker()

        with pytest.raises(FileNotFoundError, match="claude CLI binary not found"):
            _build_cli_args(task, worker, "sys")


# ---------------------------------------------------------------------------
# _parse_cc_output
# ---------------------------------------------------------------------------


class TestParseCcOutput:
    def test_valid_json_success(self):
        data = {
            "result": "All tests pass.",
            "total_cost_usd": 0.05,
            "usage": {"input_tokens": 1000, "output_tokens": 500},
            "num_turns": 3,
            "is_error": False,
            "session_id": "sess-123",
        }
        result = _parse_cc_output(json.dumps(data))

        assert result.success is True
        assert result.output == "All tests pass."
        assert result.tool_calls == 2  # max(0, 3 - 1)
        assert result.session_id == "sess-123"
        assert result.num_turns == 3
        assert result.metrics is not None
        assert result.metrics["tokens"] == 1500
        assert result.metrics["cost"] == 0.05
        assert result.metrics["input_tokens"] == 1000
        assert result.metrics["output_tokens"] == 500

    def test_valid_json_error_result(self):
        data = {
            "result": "Permission denied",
            "is_error": True,
            "num_turns": 1,
            "usage": {},
        }
        result = _parse_cc_output(json.dumps(data))

        assert result.success is False
        assert result.output == "Permission denied"

    def test_empty_string(self):
        result = _parse_cc_output("")
        assert result.success is False
        assert "Empty output" in result.output

    def test_whitespace_only(self):
        result = _parse_cc_output("   \n\t  ")
        assert result.success is False
        assert "Empty output" in result.output

    def test_non_json_garbage(self):
        result = _parse_cc_output("this is not json at all")
        assert result.success is False
        assert "Failed to parse" in result.output

    def test_json_with_preamble_last_line_valid(self):
        lines = [
            "Loading claude...",
            "Initializing...",
            json.dumps({
                "result": "Done!",
                "is_error": False,
                "num_turns": 2,
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "session_id": "s-abc",
            }),
        ]
        raw = "\n".join(lines)
        result = _parse_cc_output(raw)

        assert result.success is True
        assert result.output == "Done!"
        assert result.session_id == "s-abc"

    def test_multiline_no_valid_json_line(self):
        raw = "line1\nline2\nline3"
        result = _parse_cc_output(raw)
        assert result.success is False
        assert "Failed to parse" in result.output

    def test_zero_num_turns_yields_zero_tool_calls(self):
        data = {
            "result": "No tools used.",
            "is_error": False,
            "num_turns": 0,
            "usage": {"input_tokens": 50, "output_tokens": 20},
        }
        result = _parse_cc_output(json.dumps(data))
        assert result.tool_calls == 0

    def test_one_num_turn_yields_zero_tool_calls(self):
        data = {
            "result": "Single turn.",
            "is_error": False,
            "num_turns": 1,
            "usage": {"input_tokens": 50, "output_tokens": 20},
        }
        result = _parse_cc_output(json.dumps(data))
        assert result.tool_calls == 0

    def test_files_modified_extracted_from_result(self):
        data = {
            "result": "Created file: src/main.py and modified tests/test_main.py",
            "is_error": False,
            "num_turns": 4,
            "usage": {"input_tokens": 200, "output_tokens": 100},
        }
        result = _parse_cc_output(json.dumps(data))
        assert result.files_modified is not None
        assert "src/main.py" in result.files_modified

    def test_no_files_modified_returns_none(self):
        data = {
            "result": "Analysis complete. No files changed.",
            "is_error": False,
            "num_turns": 2,
            "usage": {},
        }
        result = _parse_cc_output(json.dumps(data))
        assert result.files_modified is None

    def test_missing_usage_defaults_to_zero(self):
        data = {
            "result": "ok",
            "is_error": False,
        }
        result = _parse_cc_output(json.dumps(data))
        assert result.metrics is not None
        assert result.metrics["tokens"] == 0
        assert result.metrics["input_tokens"] == 0
        assert result.metrics["output_tokens"] == 0


# ---------------------------------------------------------------------------
# _extract_files_modified
# ---------------------------------------------------------------------------


class TestExtractFilesModified:
    def test_created_file_pattern(self):
        output = "Created file: src/utils.py"
        files = _extract_files_modified(output)
        assert "src/utils.py" in files

    def test_wrote_file_pattern(self):
        output = "Wrote file: output.txt with results"
        files = _extract_files_modified(output)
        assert "output.txt" in files

    def test_wrote_to_does_not_match(self):
        # "Wrote to X" doesn't match because regex expects optional "file:" not "to"
        output = "Wrote to output.txt with results"
        files = _extract_files_modified(output)
        assert "output.txt" not in files

    def test_modified_pattern(self):
        output = "Modified src/config.py to add defaults"
        files = _extract_files_modified(output)
        assert "src/config.py" in files

    def test_edited_pattern(self):
        output = "Edited tests/test_app.py to fix import"
        files = _extract_files_modified(output)
        assert "tests/test_app.py" in files

    def test_updated_pattern(self):
        output = "Updated README.md with new instructions"
        files = _extract_files_modified(output)
        assert "README.md" in files

    def test_file_colon_pattern(self):
        output = "File: src/parser.py"
        files = _extract_files_modified(output)
        assert "src/parser.py" in files

    def test_path_colon_pattern(self):
        output = "Path: lib/helpers.js"
        files = _extract_files_modified(output)
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
        output = "Everything looks fine, no changes needed."
        files = _extract_files_modified(output)
        assert files == []

    def test_deduplicates_paths(self):
        output = (
            "Created file: src/main.py\n"
            "Modified src/main.py"
        )
        files = _extract_files_modified(output)
        assert files.count("src/main.py") == 1

    def test_strips_surrounding_quotes(self):
        output = "Created file: 'src/quoted.py'"
        files = _extract_files_modified(output)
        assert "src/quoted.py" in files


# ---------------------------------------------------------------------------
# create_cc_spawn_fn
# ---------------------------------------------------------------------------


class TestCreateCcSpawnFn:
    def test_returns_callable(self):
        fn = create_cc_spawn_fn(working_dir="/tmp", default_model="sonnet")
        assert callable(fn)

    def test_returned_fn_is_async(self):
        fn = create_cc_spawn_fn()
        assert asyncio.iscoroutinefunction(fn)

    @patch("attocode.integrations.swarm.cc_spawner.spawn_cc_worker")
    @pytest.mark.asyncio
    async def test_spawn_fn_delegates_to_spawn_cc_worker(self, mock_spawn):
        mock_spawn.return_value = SpawnResult(success=True, output="ok")

        fn = create_cc_spawn_fn(
            working_dir="/projects/demo",
            max_iterations=20,
        )
        task = _make_task()
        worker = _make_worker()

        result = await fn(task, worker, "system prompt")

        assert result.success is True
        mock_spawn.assert_called_once()
        call_kwargs = mock_spawn.call_args
        assert call_kwargs.kwargs["working_dir"] == "/projects/demo"
        assert call_kwargs.kwargs["max_iterations"] == 20


# =============================================================================
# _is_test_command
# =============================================================================


class TestIsTestCommand:
    def test_pytest(self):
        assert _is_test_command("pytest tests/") is True

    def test_npm_test(self):
        assert _is_test_command("npm test") is True

    def test_go_test(self):
        assert _is_test_command("go test ./...") is True

    def test_cargo_test(self):
        assert _is_test_command("cargo test") is True

    def test_python_m_pytest(self):
        assert _is_test_command("python -m pytest --tb=short") is True

    def test_make_test(self):
        assert _is_test_command("make test") is True

    def test_jest(self):
        assert _is_test_command("npx jest") is True

    def test_vitest(self):
        assert _is_test_command("vitest run") is True

    def test_not_test_command(self):
        assert _is_test_command("ls -la") is False

    def test_not_test_build(self):
        assert _is_test_command("npm run build") is False


# =============================================================================
# _extract_tool_actions
# =============================================================================


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
        assert len(bash_actions) == 1  # deduplicated

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


# =============================================================================
# _extract_test_output
# =============================================================================


class TestExtractTestOutput:
    def test_no_test_actions(self):
        from attocode.integrations.swarm.types import ToolAction
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="ls", output_summary="files", is_test_execution=False),
        ]
        assert _extract_test_output(actions) is None

    def test_collects_test_output(self):
        from attocode.integrations.swarm.types import ToolAction
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="2 passed", is_test_execution=True),
        ]
        result = _extract_test_output(actions)
        assert result is not None
        assert "2 passed" in result
        assert "pytest" in result

    def test_empty_list(self):
        assert _extract_test_output([]) is None

    def test_truncates_long_output(self):
        from attocode.integrations.swarm.types import ToolAction
        actions = [
            ToolAction(tool_name="Bash", arguments_summary="pytest", output_summary="x" * 6000, is_test_execution=True),
        ]
        result = _extract_test_output(actions)
        assert result is not None
        assert len(result) <= 5000


# =============================================================================
# _parse_cc_output populates tool_actions/test_output
# =============================================================================


class TestParseCcOutputToolActions:
    def test_result_with_test_command(self):
        data = json.dumps({
            "result": "I ran:\n```bash\npytest tests/\n```\n2 passed, 0 failed",
            "is_error": False,
            "num_turns": 3,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })
        result = _parse_cc_output(data)
        assert result.tool_actions is not None
        assert len(result.tool_actions) >= 1
        assert result.test_output is not None
        assert "pytest" in result.test_output

    def test_result_without_test_commands(self):
        data = json.dumps({
            "result": "I created the file successfully.",
            "is_error": False,
            "num_turns": 2,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })
        result = _parse_cc_output(data)
        assert result.test_output is None
