"""Integration test: single-turn agent execution with mock provider."""

from __future__ import annotations

import pytest

from attocode.providers.mock import MockProvider
from attocode.tools.registry import ToolRegistry
from attocode.tools.standard import create_standard_registry
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)


class TestSingleTurnExecution:
    """Test a full single-turn agent execution: prompt → LLM → tool → LLM → response."""

    @pytest.mark.asyncio
    async def test_simple_response(self) -> None:
        """LLM returns a text response with no tool calls."""
        provider = MockProvider()
        provider.add_response(content="The answer is 42.")

        messages = [Message(role=Role.USER, content="What is the answer?")]
        response = await provider.chat(messages)

        assert response.content == "The answer is 42."
        assert response.stop_reason == StopReason.END_TURN
        assert not response.has_tool_calls

    @pytest.mark.asyncio
    async def test_tool_call_and_response(self, tmp_workdir) -> None:
        """Full loop: LLM calls a tool, gets result, then produces final response."""
        registry = create_standard_registry(str(tmp_workdir))

        # Create a test file
        test_file = tmp_workdir / "hello.txt"
        test_file.write_text("Hello from the test file!")

        # Step 1: LLM requests to read a file
        provider = MockProvider()
        provider.add_tool_response(
            [ToolCall(id="tc_1", name="read_file", arguments={"path": str(test_file)})],
            content="Let me read that file.",
        )
        provider.add_response(content="The file says: Hello from the test file!")

        # First LLM call
        messages = [Message(role=Role.USER, content="Read hello.txt")]
        response1 = await provider.chat(messages)
        assert response1.has_tool_calls
        assert response1.tool_calls[0].name == "read_file"

        # Execute the tool
        tc = response1.tool_calls[0]
        tool_result = await registry.execute(tc.name, tc.arguments)
        assert not tool_result.is_error
        assert "Hello from the test file!" in tool_result.result

        # Second LLM call with tool result
        messages.append(Message(
            role=Role.ASSISTANT,
            content=response1.content,
            tool_calls=response1.tool_calls,
        ))
        messages.append(Message(
            role=Role.TOOL,
            content=tool_result.result,
            tool_call_id=tc.id,
        ))
        response2 = await provider.chat(messages)
        assert not response2.has_tool_calls
        assert "Hello from the test file!" in response2.content

    @pytest.mark.asyncio
    async def test_tool_batch_execution(self, tmp_workdir) -> None:
        """Test executing multiple tools in parallel."""
        registry = create_standard_registry(str(tmp_workdir))

        # Create test files
        (tmp_workdir / "a.txt").write_text("content A")
        (tmp_workdir / "b.txt").write_text("content B")

        calls = [
            ("tc_1", "read_file", {"path": str(tmp_workdir / "a.txt")}),
            ("tc_2", "read_file", {"path": str(tmp_workdir / "b.txt")}),
        ]
        results = await registry.execute_batch(calls)
        assert len(results) == 2
        assert not results[0].is_error
        assert not results[1].is_error
        assert "content A" in results[0].result
        assert "content B" in results[1].result

    @pytest.mark.asyncio
    async def test_write_and_read_cycle(self, tmp_workdir) -> None:
        """Test writing a file and reading it back."""
        registry = create_standard_registry(str(tmp_workdir))

        # Write
        write_result = await registry.execute("write_file", {
            "path": str(tmp_workdir / "output.txt"),
            "content": "written by agent",
        })
        assert not write_result.is_error

        # Read back
        read_result = await registry.execute("read_file", {
            "path": str(tmp_workdir / "output.txt"),
        })
        assert not read_result.is_error
        assert "written by agent" in read_result.result

    @pytest.mark.asyncio
    async def test_edit_cycle(self, tmp_workdir) -> None:
        """Test editing a file."""
        registry = create_standard_registry(str(tmp_workdir))

        # Create file
        (tmp_workdir / "edit_me.txt").write_text("hello world")

        # Edit
        edit_result = await registry.execute("edit_file", {
            "path": str(tmp_workdir / "edit_me.txt"),
            "old_string": "world",
            "new_string": "python",
        })
        assert not edit_result.is_error

        # Verify
        read_result = await registry.execute("read_file", {
            "path": str(tmp_workdir / "edit_me.txt"),
        })
        assert "python" in read_result.result
        assert "world" not in read_result.result

    @pytest.mark.asyncio
    async def test_bash_execution(self, tmp_workdir) -> None:
        """Test bash tool execution."""
        registry = create_standard_registry(str(tmp_workdir))
        result = await registry.execute("bash", {"command": "echo 'hello from bash'"})
        assert not result.is_error
        assert "hello from bash" in result.result

    @pytest.mark.asyncio
    async def test_grep_search(self, tmp_workdir) -> None:
        """Test grep tool execution."""
        (tmp_workdir / "code.py").write_text("def foo():\n    return 42\n")
        registry = create_standard_registry(str(tmp_workdir))
        result = await registry.execute("grep", {
            "pattern": "def foo",
            "path": str(tmp_workdir),
        })
        assert not result.is_error
        assert "foo" in result.result

    @pytest.mark.asyncio
    async def test_provider_with_options(self) -> None:
        """Test provider respects chat options."""
        provider = MockProvider()
        provider.add_response(content="response with options")

        messages = [Message(role=Role.USER, content="test")]
        options = ChatOptions(
            model="test-model",
            max_tokens=100,
            temperature=0.5,
        )
        response = await provider.chat(messages, options)
        assert response.content == "response with options"

        # Verify options were passed through
        _, recorded_opts = provider.call_history[0]
        assert recorded_opts.model == "test-model"
        assert recorded_opts.max_tokens == 100

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self) -> None:
        """Test multi-turn conversation with mock provider."""
        provider = MockProvider()
        provider.add_response(content="I can help with that.")
        provider.add_response(content="Here is the result.")

        messages = [Message(role=Role.USER, content="Help me")]
        r1 = await provider.chat(messages)
        messages.append(Message(role=Role.ASSISTANT, content=r1.content))
        messages.append(Message(role=Role.USER, content="Thanks, now do this"))
        r2 = await provider.chat(messages)

        assert r1.content == "I can help with that."
        assert r2.content == "Here is the result."
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_token_tracking(self) -> None:
        """Test that token usage is properly tracked."""
        provider = MockProvider()
        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150, cost=0.01)
        provider.add_response(content="tracked", usage=usage)

        messages = [Message(role=Role.USER, content="test")]
        response = await provider.chat(messages)
        assert response.usage.input_tokens == 100
        assert response.usage.output_tokens == 50
        assert response.usage.cost == 0.01
